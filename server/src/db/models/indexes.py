"""Index membership (Excel: Indexes). Replaces nifty_500_list."""
from tortoise import fields
from tortoise.models import Model


class IndexMembership(Model):
    id = fields.IntField(pk=True)
    company = fields.ForeignKeyField(
        "models.CompanyInfo",
        related_name="index_memberships",
        null=True,
        on_delete=fields.SET_NULL,
    )
    scrip_code = fields.CharField(max_length=32, index=True)
    index_name = fields.CharField(max_length=64, index=True)  # nifty500 | BSE500
    timestamp_date = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "Indexes"
        unique_together = (("scrip_code", "index_name"),)
