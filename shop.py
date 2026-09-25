import random
import string
from decimal import Decimal, InvalidOperation
import discord
from database import Session, User, Order, Product


### await interaction.response.defer(ephemeral=True) -- Always above slow process. [ephemeral == only the user sees who actioned - next follow up message inherits]

class ShopButtons(discord.ui.View):
    def __init__(self, bot, guild_id, owner_role_id, order_category_id):
        self.bot = bot
        self.guild_id = guild_id
        self.owner_role_id = owner_role_id
        self.order_category_id = order_category_id

        super().__init__(timeout=None)

    @discord.ui.button(label="Buy", emoji="💵", style=discord.ButtonStyle.primary, custom_id="shop:buy")
    async def buy(self, interaction, button):
        member = interaction.user
        item_embed = interaction.message.embeds[0]

        product_id = int(item_embed.footer.text.split(": ")[1])

        await interaction.response.defer(ephemeral=True)

        async with Session() as session:
            product = await Product.get_product(db_session=session, product_id=product_id)

            if product is None:
                return await interaction.followup.send(f"{member.mention} - Sorry, this item no longer exists.",
                                                       ephemeral=True)

            stock = product.stock
            price = product.price
            product_id = product.product_id

            if stock <= 0:
                return await interaction.followup.send(f"{member.mention} - Sorry this item is out of stock. Check back later!", ephemeral=True)

            db_user = await User.get_user(db_session=session, user_id=member.id)

            if not db_user:
                return await interaction.followup.send(f"{member.mention} - Sorry you have no account. Unable to place order.", ephemeral=True)

            if db_user.balance < price:
                return await interaction.followup.send(
                    f"{member.mention} - Sorry you have Insufficient funds. Unable to place order.",
                    ephemeral=True,
                )

            order = await Order.add_order(db_session=session, user_id=member.id, product_id=product_id, should_commit=False)

            guild = self.bot.get_guild(self.guild_id)
            admin_role = guild.get_role(self.owner_role_id)
            category = guild.get_channel(self.order_category_id)

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                member: discord.PermissionOverwrite(read_messages=True),
                admin_role: discord.PermissionOverwrite(read_messages=True),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }

            channel = await guild.create_text_channel(
                f"order-{order.id}-{member.display_name}",
                overwrites=overwrites,
                category=category,
            )

            order.channel_id = channel.id
            await session.commit()

            item_embed = interaction.message.embeds[0]
            item_embed.description = f"**{item_embed.title}**"
            item_embed.title = "Order Requested"
            item_embed.set_footer(text=f"Order ID: {order.id}")

            await channel.send(f"Thanks for your order, {member.mention}! One of the {admin_role.mention} will review and confirm your order shortly. Please note that availability is subject to final approval.")
            await channel.send(embed=item_embed, view=CancelOrderView(owner_role_id=self.owner_role_id))


class CancelOrderView(discord.ui.View):
    def __init__(self, owner_role_id):
        self.owner_role_id = owner_role_id
        super().__init__(timeout=None)

    @discord.ui.button(label="Cancel Order", style=discord.ButtonStyle.red, custom_id="cancel:order")
    async def cancel_order(self, interaction, button):
        button.disabled = True
        await interaction.response.edit_message(view=self)
        member = interaction.user

        async with Session() as session:
            order = await Order.find_by_channel(session, interaction.channel.id)

            if not order:
                return await interaction.followup.send("No order found for this ticket.", ephemeral=True)

            if order.user_id != member.id:
                button.disabled = False
                await interaction.edit_original_response(view=self)
                return await interaction.followup.send("Only the buyer can cancel this order.", ephemeral=True)

            deleted = await Order.delete_order(session, order.id)

            if not deleted:
                return await interaction.followup.send("This order was already cancelled.", ephemeral=True)

            await interaction.channel.set_permissions(member, read_messages=True, send_messages=False)


            await interaction.message.edit(view=self)

            owner_role = interaction.guild.get_role(int(self.owner_role_id))

            embed = discord.Embed(
                title="Order Cancelled",
                description=f"{member.mention} Your order has been cancelled. This channel will be read only for you. {owner_role.mention}",
                color=discord.Color.red()
            )

            await interaction.channel.send(embed=embed)




class AddItemModal(discord.ui.Modal, title="Add Item"):
    def __init__(self, *args, **kwargs):
        self.bot = kwargs.pop("bot")
        self.forum_channel = kwargs.pop("forum_channel")
        self.guild = kwargs.pop("guild_id")
        self.owner_role_id = kwargs.pop("owner_role_id")
        self.order_category_id = kwargs.pop("order_category_id")
        super().__init__(*args, **kwargs)

    item_title = discord.ui.TextInput(label="Item Title", placeholder="Enter the item title")
    item_description = discord.ui.TextInput(label="Card Description", placeholder="Enter the item description")
    price_stock = discord.ui.TextInput(label="Price, Stock", placeholder="100, 10")
    tags = discord.ui.Label(text="Tags (comma separated)", component=discord.ui.TextInput(placeholder="Amazon, 100-199PTS", required=False))
    image = discord.ui.Label(text="Image", component=discord.ui.FileUpload(max_values=1, required=True))

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)

        parts = [ps.strip() for ps in self.price_stock.value.split(",")]
        if len(parts) != 2:
            return await interaction.followup.send("Format must be `price, stock`, like `100, 10`.", ephemeral=True)

        try:
            price = Decimal(parts[0])
            stock = int(parts[1])
        except (InvalidOperation, ValueError):
            return await interaction.followup.send("Format must be `price, stock`, like `100, 10`.", ephemeral=True)

        if price <= 0 or stock < 0:
            return await interaction.followup.send("Price must be above 0 and stock can't be negative.", ephemeral=True)

        forum = self.bot.get_channel(self.forum_channel)
        file = await self.image.component.values[0].to_file(filename="item.png")

        embed = discord.Embed(
            title=self.item_title.value,
            description=f"Redeem {price} Betro Tokens for a {self.item_description.value}",
            color=discord.Color.green()
        )

        embed.set_author(name=self.bot.user.name, icon_url=self.bot.user.display_avatar.url)
        embed.add_field(name="Price", value=f"{price} Betro Tokens")
        embed.add_field(name="Stock", value=stock)
        embed.set_image(url="attachment://item.png")

        tag_wanted = [tag.strip().lower() for tag in self.tags.component.value.split(",")]
        tags = [tag for tag in forum.available_tags if tag.name.lower() in tag_wanted]

        post = await forum.create_thread(
            name=f"{self.item_title.value} ({price} Betro Tokens)",
            embed=embed,
            file=file,
            view=ShopButtons(bot=self.bot, guild_id=self.guild, owner_role_id=self.owner_role_id, order_category_id=self.order_category_id),
            applied_tags=tags[:5]
        )

        async with Session() as session:
            product_id = await Product.add_product(db_session=session, name=self.item_title.value, price=price, stock=stock, thread_id=post.thread.id)

        embed.set_footer(text=f"Product ID: {product_id}")
        await post.message.edit(embed=embed)

        await interaction.followup.send(f"Added Item {self.item_title.value}", ephemeral=True)
