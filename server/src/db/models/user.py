"""Users and roles (Excel: User_Roles, User)."""
from tortoise import fields
from tortoise.models import Model


class UserRole(Model):
    id = fields.IntField(pk=True)
    role = fields.CharField(max_length=64, unique=True)

    class Meta:
        table = "User_Roles"

    def __str__(self) -> str:
        return self.role


class User(Model):
    id = fields.IntField(pk=True)
    role = fields.ForeignKeyField(
        "models.UserRole",
        related_name="users",
        on_delete=fields.RESTRICT,
    )
    name = fields.CharField(max_length=255)
    username = fields.CharField(max_length=255, unique=True)
    password = fields.CharField(max_length=255)

    class Meta:
        table = "User"

    def __str__(self) -> str:
        return self.username
