"""Industry lookup table (Excel: Industry)."""
from tortoise import fields
from tortoise.models import Model


class Industry(Model):
    id = fields.IntField(pk=True)
    industry_name = fields.CharField(max_length=255, unique=True)

    class Meta:
        table = "Industry"

    def __str__(self) -> str:
        return self.industry_name
