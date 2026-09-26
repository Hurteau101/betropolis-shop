from typing import Optional
import discord
from discord import app_commands, Interaction
from database import Session, User, Order, Product


class WrongChannel(app_commands.CheckFailure):
    pass

async def get_user_information(interaction:discord.Interaction, user_id: Optional[str] = None, display_name: Optional[str] = None):
    """Find the discord user"""
    if user_id:
        return interaction.guild.get_member(int(user_id))
    elif display_name:
        return discord.utils.find(
            lambda member: member.display_name.lower() == display_name.lower(),
            interaction.guild.members
        )

    return None


async def get_single_user(interaction: discord.Interaction, member: discord.Member, error_message: str, get_orders: bool):
    """Get a single user"""
    async with Session() as session:
        db_user = await User.get_user(db_session=session, user_id=member.id)
        if not db_user:
            await interaction.response.send_message(error_message, ephemeral=True)
            return None

        if get_orders:
            user_orders = await User.get_user_orders(db_session=session, user_id=member.id)
            return db_user, user_orders

    return db_user


def base_user_embed(title: str, member: discord.Member, discord_client: discord.Client, description: str = ''):
    """Creates a base embed for the bot"""
    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.green()
    )

    embed.set_author(name=discord_client.user.name, icon_url=discord_client.user.display_avatar.url)
    embed.set_thumbnail(url=member.display_avatar.url)

    return embed

def base_admin_profile_embed(member: discord.Member, db_user: User, bot: discord.Client, user_orders=None):
    embed = base_user_embed(title=f"{member.display_name}'s Profile", member=member, discord_client=bot)
    embed.add_field(name="User ID", value=member.id, inline=False)
    embed.add_field(name="Balance", value=f"{db_user.balance} Betro {'Tokens' if db_user.balance != 1 else 'Token' }", inline=False)

    if user_orders:
        open_orders = sum(1 for order in user_orders if not order.completed)
        embed.add_field(name="Open Orders", value=open_orders, inline=False)
        embed.add_field(name="Total Orders", value=len(user_orders), inline=False)
        lines = [
            f"#{order.id:<4} {order.product.name[:20]:<20} {order.product.price:g} Tokens"
            for order in user_orders
            if not order.completed
        ]

        if lines:
            embed.add_field(name="Open Orders", value="```\n" + "\n".join(lines) + "\n```", inline=False)

    embed.add_field(name="User Created At", value=f"{db_user.created_date.strftime('%Y-%m-%d %H:%M:%S')}", inline=False)

    return embed

def is_in_allowed_category(category_ids: int | str | list):
    if isinstance(category_ids, (str, int)):
        category_ids = [int(category_ids)]

    async def check_category(interaction: Interaction):
        if interaction.channel.category.id not in category_ids:
            raise WrongChannel()

        return True

    return app_commands.check(check_category)

def is_in_allowed_channels(channel_ids: int | str | list):
    if isinstance(channel_ids, (str, int)):
        channel_ids = [int(channel_ids)]

    async def check_channel(interaction: Interaction) -> bool:
        if interaction.channel_id not in channel_ids:
            raise WrongChannel()

        return True

    return app_commands.check(check_channel)