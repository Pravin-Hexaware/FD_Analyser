"""Screener (Excel: Screener)."""
from tortoise import fields
from tortoise.models import Model


class Screener(Model):
    id = fields.IntField(pk=True)
    screener_name = fields.CharField(max_length=255)
    query = fields.TextField(null=True)
    company_ids = fields.TextField(null=True)  # JSON list
    industry_ids = fields.TextField(null=True)
    user = fields.ForeignKeyField(
        "models.User",
        related_name="screeners",
        null=True,
        on_delete=fields.SET_NULL,
    )

    class Meta:
        table = "Screener"
