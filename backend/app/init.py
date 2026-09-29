from .config import settings
from .seed import seed_demo

if __name__ == "__main__":
    settings.validate()
    if settings.seed_demo:
        seed_demo()
