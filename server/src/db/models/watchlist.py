"""WatchList (Excel: WatchList)."""
from tortoise import fields
from tortoise.models import Model


class WatchList(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=255)
    company_ids = fields.TextField(null=True)  # JSON list
    user = fields.ForeignKeyField(
        "models.User",
        related_name="watchlists",
        null=True,
        on_delete=fields.SET_NULL,
    )

    class Meta:
        table = "WatchList"
