"""Company master (Excel: company_info)."""
from tortoise import fields
from tortoise.models import Model


class CompanyInfo(Model):
    id = fields.IntField(pk=True)
    company_name = fields.CharField(max_length=512)
    symbol = fields.CharField(max_length=64, null=True)
    scrip_code = fields.CharField(max_length=32, unique=True)
    isin_no = fields.CharField(max_length=32, null=True)
    industry = fields.ForeignKeyField(
        "models.Industry",
        related_name="companies",
        null=True,
        on_delete=fields.SET_NULL,
    )

    class Meta:
        table = "company_info"

    def __str__(self) -> str:
        return f"{self.symbol or ''} ({self.scrip_code})"
