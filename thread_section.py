import os
from typing import Optional
import discord
from discord import app_commands
from dotenv import load_dotenv
from discord.ext import commands
from helpers import is_in_allowed_channels, base_user_embed, get_single_user, get_user_information, WrongChannel, \
    base_admin_profile_embed, is_in_allowed_category
from orders import GiftCardValueForm, GiftCardEmailView, PsychicalView, CloseConfirmationModal, remove_cancel_button
from shop import AddItemModal, ShopButtons, CancelOrderView, EditItemModal
from database import Session, User, Order, Product

load_dotenv()

def load_configs():
    bot_token = os.getenv("BOT_TOKEN")

    if not bot_token:
        raise ValueError("BOT_TOKEN is not set in the environment variables")

    is_production = os.getenv("IS_PRODUCTION", '').lower() == "true"

    if is_production:
        guild_id = os.getenv("GUILD_ID")
        forum_channel_id = os.getenv("FORUM_CHANNEL_ID")
        allowed_command_channel = os.getenv("ALLOWED_COMMAND_CHANNEL")
        owner_role_id = os.getenv("OWNER_ROLE_ID")
        order_category_id = os.getenv("ORDER_CATEGORY_ID")
    else:
        guild_id = os.getenv("TEST_GUILD_ID")
        forum_channel_id = os.getenv("TEST_FORUM_CHANNEL_ID")
        allowed_command_channel = os.getenv("TEST_ALLOWED_COMMAND_CHANNEL")
        owner_role_id = os.getenv("TEST_OWNER_ROLE_ID")
        order_category_id = os.getenv("TEST_ORDER_CATEGORY_ID")

    if not forum_channel_id:
        raise ValueError("FORUM_CHANNEL_ID is not set in the environment variables")

    if not guild_id:
        raise ValueError("GUILD_ID is not set in the environment variables")

    return {
        "bot_token": bot_token,
        "is_production": is_production,
        "guild_id": int(guild_id),
        "forum_channel_id": int(forum_channel_id),
        "allowed_command_channel": int(allowed_command_channel),
        "owner_role_id": int(owner_role_id),
        "order_category_id": int(order_category_id)
    }

CONFIGS = load_configs()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)


@bot.event
async def on_ready():
    guild = discord.Object(id=CONFIGS["guild_id"])
    bot.tree.copy_global_to(guild=guild)
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    synced = await bot.tree.sync(guild=guild)
    print(f"Synced {len(synced)} command(s) to the server")
    print(f"We have logged in as {bot.user}")

@bot.event
async def setup_hook():
    bot.add_view(ShopButtons(bot=bot, guild_id=CONFIGS["guild_id"], owner_role_id=CONFIGS["owner_role_id"], order_category_id=CONFIGS["order_category_id"]))
    bot.add_view(GiftCardEmailView())
    bot.add_view(PsychicalView())
    bot.add_view(CancelOrderView(owner_role_id=CONFIGS["owner_role_id"]))

@bot.event
async def on_member_join(member):
    """Add a new member to the database when they join the server."""
    async with Session() as session:
        await User.add_user(session, member.id)


@bot.tree.command(name="add-user")
@is_in_allowed_channels(CONFIGS["allowed_command_channel"])
@app_commands.checks.has_role(CONFIGS["owner_role_id"])
@app_commands.describe(
    user_id="The ID of the user to add.",
)
async def add_user(interaction: discord.Interaction, user_id: str):
    try:
        uid = int(user_id)
    except ValueError:
        await interaction.response.send_message("That's not a valid user ID.", ephemeral=True)
        return

    async with Session() as session:
        user = await User.add_user(session, uid)
        if not user:
            await interaction.response.send_message("User already exists in the database.", ephemeral=True)
            return

    await interaction.response.send_message(f"Added user with ID {uid} to the database.")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message(
            "You don't have permission to use this command.", ephemeral=True
        )
    elif isinstance(error, WrongChannel):
        await interaction.response.send_message(
            "You can't use this command here.", ephemeral=True
        )
    else:
        raise error


@bot.tree.command(name="bot-help")
@is_in_allowed_channels(CONFIGS["allowed_command_channel"])
@app_commands.checks.has_role(CONFIGS["owner_role_id"])
async def help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Help Documentation",
        description=f"Break down of different commands",
        color=discord.Color.green()
    )

    embed.add_field(
        name="Token Commands",
        value=(
            "`/add-tokens` - Add tokens to a user\n"
            "`/subtract-tokens` - Remove tokens from a user\n"
        ),
        inline=False,
    )

    embed.add_field(
        name="User Commands",
        value=(
            "`/check-balance` - Check current balance"
        ),
        inline=False,
    )

    embed.add_field(
        name="Item Commands",
        value=(
            "`/add-item` - Add an item to the shop"
        ),
        inline=False,
    )

    embed.add_field(
        name="Profile Commands",
        value=(
            "`/get-user` - Display User Information\n"
            "`/add-user` - Add User Information"
        ),
        inline=False,
    )

    embed.add_field(
        name="Order Commands",
        value=(
            "`/reject-order` - Rejects the order\n"
            "`/approve-order` - Approve the order\n"
            "`/close-order` - Close the order and delete channel\n"
        ),
        inline=False,
    )

    embed.set_author(name=bot.user.name, icon_url=bot.user.display_avatar.url)
    embed.set_thumbnail(url=bot.user.display_avatar.url)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="check-balance")
async def check_balance(interaction: discord.Interaction):
    """User can check balance"""
    member = interaction.user
    db_user = await get_single_user(interaction, member, "We could not find your account. Please contact one of the owners")
    if not db_user:
        return

    embed = base_user_embed(title=f"{member.display_name}'s Profile", member=member, discord_client=bot)
    embed.add_field(name="Balance", value=f"{db_user.balance} Betro {'Tokens' if db_user.balance != 1 else 'Token' }", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="add-tokens")
@is_in_allowed_channels(CONFIGS["allowed_command_channel"])
@app_commands.checks.has_role(CONFIGS["owner_role_id"])
@app_commands.describe(
    amount="The amount of tokens to add.",
    user_id = "The ID of the user to add tokens",
    display_name = "The display name of the user to add tokens"
)
async def add_tokens(interaction: discord.Interaction, amount: int, user_id: Optional[str] = None, display_name: Optional[str] = None):
    if not amount:
        return

    if not user_id and not display_name:
        await interaction.response.send_message("You must provide either a user ID or a display name.", ephemeral=True)
        return

    member = await get_user_information(interaction, user_id, display_name)
    if not member:
        return

    async with Session() as session:
        db_user = await User.add_tokens(db_session=session, user_id=member.id, amount=amount)

    if not db_user:
        return

    embed = base_admin_profile_embed(member=member, db_user=db_user, bot=bot)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="subtract-tokens")
@is_in_allowed_channels(CONFIGS["allowed_command_channel"])
@app_commands.checks.has_role(CONFIGS["owner_role_id"])
@app_commands.describe(
    amount="The amount of tokens to subtract.",
    user_id = "The ID of the user to subtract tokens",
    display_name = "The display name of the user to subtract tokens"
)
async def subtract_tokens(interaction: discord.Interaction, amount: int, user_id: Optional[str] = None, display_name: Optional[str] = None):
    if not amount:
        return

    if not user_id and not display_name:
        await interaction.response.send_message("You must provide either a user ID or a display name.", ephemeral=True)
        return

    member = await get_user_information(interaction, user_id, display_name)
    if not member:
        return

    async with Session() as session:
        db_user = await User.subtract_tokens(db_session=session, user_id=member.id, amount=amount)

    if not db_user:
        await interaction.response.send_message("User will be in the negative, please correct", ephemeral=True)
        return

    embed = base_admin_profile_embed(member=member, db_user=db_user, bot=bot)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="get-user")
@app_commands.checks.has_role(CONFIGS["owner_role_id"])
@is_in_allowed_channels(CONFIGS["allowed_command_channel"])
@app_commands.describe(
    user_id="The ID of the user to get information about.",
    display_name="The display name of the user to get information about."
)
async def user_look_up(interaction: discord.Interaction, user_id: Optional[str] = None, display_name: Optional[str] = None):
    if not user_id and not display_name:
        await interaction.response.send_message("You must provide either a user ID or a display name.", ephemeral=True)
        return

    member = await get_user_information(interaction, user_id, display_name)

    if not member:
        await interaction.followup.send("User not found.", ephemeral=True)

    db_user, user_orders = await get_single_user(interaction, member, "User not found in the database.", get_orders=True)

    if not db_user:
        return

    embed = base_admin_profile_embed(member=member, db_user=db_user, bot=bot, user_orders=user_orders)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="reject-order")
@app_commands.checks.has_role(CONFIGS["owner_role_id"])
@is_in_allowed_category(CONFIGS["order_category_id"])
@app_commands.describe(
    reason="The reason for rejecting the order."
)
async def reject_order(interaction: discord.Interaction, reason: str):
    async with Session() as session:
        order = await Order.find_by_channel(session, interaction.channel.id)

        if order is None:
            return await interaction.response.send_message("No order found for this ticket.", ephemeral=True)

        updated_order = await Order.update_order(
            db_session=session,
            order_id=order.id,
            completed=False,
            is_rejected=True,
            rejected_by=interaction.user.id,
            reject_reason=reason,
            auto_commit=True,
        )

        if not updated_order:
            return await interaction.response.send_message("Failed to update order.", ephemeral=True)

    user = interaction.guild.get_member(int(order.user_id))
    admin_user = interaction.user

    await remove_cancel_button(interaction.channel)

    embed = discord.Embed(
        title="Order Rejected",
        description=f"{user.mention} Your order has been rejected by {admin_user.display_name}.",
        color=discord.Color.red()
    )

    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Additional Details", value="If you have any questions, please contact one of the owners or type here", inline=False)

    return await interaction.response.send_message(embed=embed)

@bot.tree.command(name="approve-order")
@app_commands.checks.has_role(CONFIGS["owner_role_id"])
@is_in_allowed_category(CONFIGS["order_category_id"])
@app_commands.choices(order_type=[
    app_commands.Choice(name="Gift Card Code", value="gift_card"),
    app_commands.Choice(name="Gift Card Email", value="gift_card_email"),
    app_commands.Choice(name="Physical Product", value="physical_product")
])
async def approve_order(interaction: discord.Interaction, order_type: str):
    async with Session() as session:
        order = await Order.find_by_channel(session, interaction.channel.id)

    if order is None:
        return await interaction.response.send_message("No order found for this ticket.", ephemeral=True)

    user = interaction.guild.get_member(int(order.user_id))
    admin_user = interaction.user

    if order_type.lower() == "gift_card":
        await interaction.response.send_modal(GiftCardValueForm(bot=bot, order_id=order.id))
    elif order_type.lower() == "gift_card_email":
        await interaction.response.send_message(
            f"{user.mention} To finalize your order, please fill out this form when you have time!",
            view=GiftCardEmailView(bot=bot, user=user, order_id=order.id, admin_user=admin_user),
        )
    else:
        await interaction.response.send_message(
            f"{user.mention} To finalize your order, please fill out this form when you have time!",
            view=PsychicalView(bot=bot, user=user, order_id=order.id, admin_user=admin_user),
        )

@bot.tree.command(name="close-order")
@app_commands.checks.has_role(CONFIGS["owner_role_id"])
@is_in_allowed_category(CONFIGS["order_category_id"])
async def close_order(interaction: discord.Interaction):
    async with Session() as session:
        order = await Order.find_by_channel(session, interaction.channel.id)

        if order is None:
            return await interaction.response.send_message("No order found for this ticket.", ephemeral=True)

        if not (order.completed or order.order_rejected or order.order_cancelled):
            return await interaction.response.send_message("Order needs to be completed or rejected before closing.",
                                                           ephemeral=True)

    return await interaction.response.send_modal(CloseConfirmationModal())

@bot.tree.command(name="add-item")
@app_commands.checks.has_role(CONFIGS["owner_role_id"])
@is_in_allowed_channels(CONFIGS["allowed_command_channel"])
async def add_item(interaction: discord.Interaction):
    await interaction.response.send_modal(AddItemModal(
        bot=bot,
        forum_channel=CONFIGS["forum_channel_id"],
        guild_id=CONFIGS["guild_id"],
        owner_role_id=CONFIGS["owner_role_id"],
        order_category_id=CONFIGS["order_category_id"]
    ))

@bot.tree.command(name="edit-item")
@app_commands.checks.has_role(CONFIGS["owner_role_id"])
@is_in_allowed_channels(CONFIGS["allowed_command_channel"])
@app_commands.describe(
    product_id="The product ID to edit"
)
async def add_item(interaction: discord.Interaction, product_id: int):
    async with Session() as session:
        product = await Product.get_product(session, product_id)
        if not product:
            return await interaction.response.send_message("Product not found.", ephemeral=True)

    return await interaction.response.send_modal(EditItemModal(product))

bot.run(CONFIGS["bot_token"])