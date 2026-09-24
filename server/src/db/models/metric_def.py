"""Metric catalog (Excel: Metrics)."""
from tortoise import fields
from tortoise.models import Model


class MetricDefinition(Model):
    id = fields.IntField(pk=True)
    metric_category = fields.CharField(max_length=64)  # quarterly | annual
    sub_category = fields.CharField(max_length=64)  # quarterly | P_L | Balancesheet | cashflow
    particulars = fields.CharField(max_length=255)

    class Meta:
        table = "Metrics"

    def __str__(self) -> str:
        return f"{self.metric_category}/{self.sub_category}: {self.particulars}"
