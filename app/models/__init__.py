# Copyright © Taksheel Saini. All rights reserved. | GitHub: https://github.com/taksheelsaini | LinkedIn: https://www.linkedin.com/in/taksheelsaini/# Importing all models here ensures they are registered with SQLAlchemy's
# declarative Base before Alembic inspects the metadata.
from app.models.document import Document, Chunk  # noqa: F401
from app.models.conversation import Conversation, Message  # noqa: F401
