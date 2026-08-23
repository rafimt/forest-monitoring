import ee

from app.config import settings

ee.Initialize(project=settings.gee_project)

print("EE says:", ee.Number(21).multiply(2).getInfo())
