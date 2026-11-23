from pydantic import BaseModel


class GoogleLoginConfigOut(BaseModel):
    enabled: bool
