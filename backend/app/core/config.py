from pydantic import BaseModel


class Settings(BaseModel):
    max_review_sample: int = 100
    random_seed: int = 42


settings = Settings()

