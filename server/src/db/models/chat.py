"""Chat tables (Excel: Conversations, chat_History, chat_References, chat_personalisation)."""
from tortoise import fields
from tortoise.models import Model


class Conversation(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField(
        "models.User",
        related_name="conversations",
        null=True,
        on_delete=fields.SET_NULL,
    )
    created_time = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "Conversations"


class ChatPersonalisation(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255)
    created_from = fields.CharField(max_length=255, null=True)
    company_ids = fields.TextField(null=True)
    industry_ids = fields.TextField(null=True)
    quarterly_p_l_metrics = fields.TextField(null=True)
    balancesheet_metrics = fields.TextField(null=True)
    cashflow_metrics = fields.TextField(null=True)
    ratios_metrics = fields.TextField(null=True)
    user = fields.ForeignKeyField(
        "models.User",
        related_name="personalizations",
        null=True,
        on_delete=fields.SET_NULL,
    )

    class Meta:
        table = "chat_personalisation"


class ChatHistory(Model):
    id = fields.IntField(pk=True)
    conversation = fields.ForeignKeyField(
        "models.Conversation",
        related_name="messages",
        on_delete=fields.CASCADE,
    )
    user = fields.ForeignKeyField(
        "models.User",
        related_name="chat_messages",
        null=True,
        on_delete=fields.SET_NULL,
    )
    sequence_number = fields.IntField()
    query = fields.TextField(null=True)
    response = fields.TextField(null=True)
    reference_id = fields.IntField(null=True)
    personalise = fields.ForeignKeyField(
        "models.ChatPersonalisation",
        related_name="histories",
        null=True,
        on_delete=fields.SET_NULL,
    )
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "chat_History"
        unique_together = (("conversation", "sequence_number"),)


class ChatReference(Model):
    id = fields.IntField(pk=True)
    messages_id = fields.IntField(null=True, index=True)
    xbrl_data_ids = fields.TextField(null=True)
    news_articles = fields.TextField(null=True)
    investor_info = fields.TextField(null=True)

    class Meta:
        table = "chat_References"
