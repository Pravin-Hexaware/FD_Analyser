"""XBRL filing metadata + full parse JSON (Excel: XBRL_Data). Raw files live on disk."""
from tortoise import fields
from tortoise.models import Model


class XbrlData(Model):
    id = fields.IntField(pk=True)
    scrip_code = fields.CharField(max_length=32, index=True)
    period = fields.CharField(max_length=64, index=True)
    xbrl_link = fields.TextField()
    category = fields.CharField(max_length=16, index=True)  # std | con
    metrics_json = fields.TextField(null=True)  # full parsed document JSON
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "XBRL_Data"
        unique_together = (("scrip_code", "period", "category"),)

    def __str__(self) -> str:
        return f"{self.scrip_code} {self.period} ({self.category})"
