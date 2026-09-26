import discord
from database import User, Session, Order, Product

async def order_look_up_process(interaction: discord.Interaction, order_id: int, member: discord.Member):
    async with Session() as session:
        order = await Order.update_order(db_session=session, order_id=order_id, completed=True,
                                         completed_by=member.id)

        if order is None:
            found_order = await Order.find_order(db_session=session, order_id=order_id)
            if found_order is None:
                await interaction.followup.send("Order not found.", ephemeral=True)
                return None, None

            await interaction.followup.send("Order already completed.", ephemeral=True)
            return None, None

        product = await Product.reduce_stock(db_session=session, product_id=order.product_id)

        if product is None:
            await session.rollback()
            await interaction.followup.send("Product not found.", ephemeral=True)
            return None, None

        db_user = await User.subtract_tokens(db_session=session, user_id=order.user_id, amount=product.price,
                                             should_commit=False)

        if db_user is None:
            await session.rollback()
            await interaction.followup.send("Buyer has insufficient funds.", ephemeral=True)
            return None, None

        await session.commit()

        return order, db_user

async def update_forum(interaction, order):
    thread = interaction.guild.get_thread(order.product.thread_id)
    embed_data = await thread.fetch_message(order.product.thread_id)

    post_embed = embed_data.embeds[0]
    index, field = next((i, f) for i, f in enumerate(post_embed.fields) if f.name == "Stock")
    post_embed.set_field_at(index, name="Stock", value=str(int(field.value) - 1))
    post_embed.set_image(url="attachment://item.png")

    await embed_data.edit(embed=post_embed)

async def remove_cancel_button(channel):
    async for msg in channel.history(limit=5, oldest_first=True):
        if any(getattr(c, "custom_id", None) == "cancel:order" for row in msg.components for c in row.children):
            await msg.edit(view=None)
            break

async def customer_form_button(view_modal, interaction, view_id, disabled: bool):
    view = view_modal()

    for item in view.children:
        if getattr(item, "custom_id", None) == view_id:
            item.disabled = disabled

    await interaction.message.edit(view=view)

class GiftCardValueForm(discord.ui.Modal, title="Gift Card Code Form"):
    def __init__(self, *args, **kwargs):
        self.bot = kwargs.pop("bot")
        self.order_id = kwargs.pop("order_id")
        super().__init__(*args, **kwargs)

    gift_card_code = discord.ui.TextInput(label="Gift Card Code", placeholder="Enter the gift card code", required=True)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)

        member = interaction.user

        order, db_user = await order_look_up_process(interaction=interaction, order_id=self.order_id, member=member)

        if order is None or db_user is None:
            return

        await remove_cancel_button(interaction.channel)

        user = interaction.guild.get_member(int(db_user.user_id))

        embed = discord.Embed(
            title="Order Approved",
            description=f"{user.mention} Your order has been approved by {member.display_name}.",
            color=discord.Color.green()
        )

        embed.add_field(name="Order Details", value=f"**Gift Card Code:** {self.gift_card_code.value}", inline=False)
        embed.add_field(name="Additional Details", value="If you have any questions, please contact one of the owners or type here.", inline=False)
        embed.add_field(name="Remaining Balance", value=f"{db_user.balance} Betro Tokens", inline=False)
        embed.set_author(name=interaction.client.user.name, icon_url=interaction.client.user.display_avatar.url)
        embed.set_thumbnail(url=user.display_avatar.url)

        await update_forum(interaction, order)
        await interaction.followup.send(embed=embed)

class PersistentView(discord.ui.View):
    def __init__(self, **kwargs):
        self.bot = kwargs.pop("bot", None)
        self.user = kwargs.pop("user", None)
        self.order_id = kwargs.pop("order_id", None)
        self.admin_user = kwargs.pop("admin_user", None)
        super().__init__(timeout=None)

    async def order_checker(self, interaction):
        async with Session() as session:
            order = await Order.find_by_channel(session, interaction.channel.id)

        if order is None:
            await interaction.response.send_message("No order found for this ticket.", ephemeral=True)
            return None

        if interaction.user.id != order.user_id:
            await interaction.response.send_message("Only the buyer can fill out this form.", ephemeral=True)
            return None

        self.user = self.user or interaction.user
        self.admin_user = self.admin_user or interaction.message.interaction_metadata.user
        return order

class GiftCardEmailView(PersistentView):
    def __init__(self, *args, **kwargs):
        super().__init__(timeout=None)

    @discord.ui.button(label="Customer Form", style=discord.ButtonStyle.green, custom_id="approve:order:gift_card_form")
    async def customer_form(self, interaction, button):
        order = await self.order_checker(interaction)

        if not order:
            return

        return await interaction.response.send_modal(GiftCardEmailModal(order_id=order.id, user=self.user, bot=self.bot, admin_user=self.admin_user))


class PsychicalView(PersistentView):
    def __init__(self, *args, **kwargs):
        super().__init__(timeout=None)

    @discord.ui.button(label="Customer Form", style=discord.ButtonStyle.green, custom_id="approve:order:psychical_form")
    async def customer_form(self, interaction, button):
        order = await self.order_checker(interaction)

        if not order:
            return

        return await interaction.response.send_modal(
            PsychicalModal(order_id=order.id, user=self.user, bot=self.bot, admin_user=self.admin_user))


class PersistentModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs):
        self.bot = kwargs.pop("bot")
        self.user = kwargs.pop("user")
        self.order_id = kwargs.pop("order_id")
        self.admin_user = kwargs.pop("admin_user")
        super().__init__(*args, **kwargs)


class GiftCardEmailModal(PersistentModal, title="Gift Card Email"):
    email = discord.ui.TextInput(label="Email address", placeholder="you@example.com")

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        await customer_form_button(GiftCardEmailView, interaction, "approve:order:gift_card_form", True)

        order, db_user = await order_look_up_process(interaction=interaction, order_id=self.order_id, member=self.admin_user)

        if order is None or db_user is None:
            return

        await remove_cancel_button(interaction.channel)

        embed = discord.Embed(
            title="Order Approved",
            description=f"{self.user.mention} Your order has been approved by {self.admin_user.display_name}.",
            color=discord.Color.green()
        )

        embed.add_field(name="Email", value=self.email.value, inline=False)
        embed.add_field(
            name="Order Details",
            value="Your gift card will be delivered to the email address above. Please allow some time for the vendor to process your order, and be sure to check your spam or junk folder if it doesn't appear in your inbox.",
            inline=False,
        )
        embed.add_field(name="Additional Details", value="If you have any questions, please contact one of the owners or type here.", inline=False)
        embed.add_field(name="Remaining Balance", value=f"{db_user.balance} Betro Tokens", inline=False)

        await update_forum(interaction, order)
        await interaction.followup.send(embed=embed)

class PsychicalModal(PersistentModal, title="Physical Form"):
    full_name = discord.ui.TextInput(label="Full Name", placeholder="John Doe", required=True)
    street_address = discord.ui.TextInput(label="Street Address", placeholder="123 Main St", required=True)
    apt_suite = discord.ui.TextInput(label="Apt/Suite", placeholder="Apt 123", required=False)
    city_state_country = discord.ui.TextInput(
        label="City, State/Province, Country",
        placeholder="Los Angeles, CA, USA OR Vancouver, BC, Canada",
        required=True,
    )
    zip_postal_code = discord.ui.TextInput(label="Zip Code or Postal Code", placeholder="10001 OR K1A 0B1", required=True)

    async def on_submit(self, interaction):
        await interaction.response.defer(ephemeral=True)
        await customer_form_button(PsychicalView, interaction, "approve:order:psychical_form", disabled=True)

        order, db_user = await order_look_up_process(interaction=interaction, order_id=self.order_id, member=self.admin_user)

        if order is None or db_user is None:
            return

        await remove_cancel_button(interaction.channel)

        embed = discord.Embed(
            title="Order Approved",
            description=f"{self.user.mention} Your order has been approved by {self.admin_user.display_name}.",
            color=discord.Color.green()
        )

        embed.add_field(name="Full Name", value=self.full_name.value, inline=False)
        embed.add_field(name="Street Address", value=self.street_address.value, inline=False)

        if self.apt_suite.value:
            embed.add_field(name="Apt/Suite", value=self.apt_suite.value, inline=False)

        embed.add_field(name="City/State/Country", value=self.city_state_country.value, inline=False)
        embed.add_field(name="Zip Code or Postal Code", value=self.zip_postal_code.value, inline=False)

        embed.add_field(
            name="Order Details",
            value="Your order will be shipped to the address above. Please review it carefully and let us know in this ticket right away if anything needs to be corrected. "
                  "Shipping times may vary depending on your location.",
            inline=False,
        )
        embed.add_field(name="Additional Details", value="If you have any questions, please contact one of the owners or type here.", inline=False)
        embed.add_field(name="Remaining Balance", value=f"{db_user.balance} Betro Tokens", inline=False)

        await update_forum(interaction, order)
        await interaction.followup.send(embed=embed)




class CloseConfirmationModal(discord.ui.Modal, title="Confirm Close Order"):
    confirm_close = discord.ui.Label(
        text="Confirm channel deletion",
        description="This channel will be deleted forever and cannot be recovered.",
        component=discord.ui.Checkbox(),
    )

    async def on_submit(self, interaction):
        if self.confirm_close.component.value:
            await interaction.response.defer(ephemeral=True)
            await interaction.channel.delete()
        else:
            await interaction.response.send_message("Please confirm that you want to close this channel.", ephemeral=True)