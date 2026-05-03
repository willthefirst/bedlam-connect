# Models layer: Database schema and domain entities

The `models/` directory contains **SQLAlchemy data models** that define the database schema and constraints for the application, implementing a **relational domain model** with clear entity boundaries.

## Core philosophy: Domain-driven data modeling

Models represent **business entities** with clear relationships, enforcing data integrity through database constraints.

### What we do

- **Domain entity modeling**: Each model represents a clear business concept (User, Post)
- **Audit trail support**: Automatic timestamps (created_at, updated_at) and soft deletion (deleted_at)
- **UUID primary keys**: Secure, non-guessable identifiers for all entities
- **Database constraint enforcement**: Unique constraints and foreign key relationships

**Example**: A model with constraints:

```python
class User(BaseModel):
    __tablename__ = "users"

    username = Column(Text, unique=True, nullable=False)
```

### What we don't do

- **Business logic in models**: Models only contain data structure and relationships, no business rules
- **Computed properties with side effects**: Properties should be simple data access, not complex calculations
- **Direct API serialization**: Models are not directly returned to APIs (use schemas for that)
- **Complex validation logic**: Database constraints for data integrity, business validation in services

**Example**: Keep models focused on data structure:

```python
# Bad - business logic in model
class User(BaseModel):
    def can_perform_action(self, action: str) -> bool:  # Business logic
        # ... complex business logic

# Good - data structure only
class User(BaseModel):
    __tablename__ = "users"
    username = Column(Text, unique=True, nullable=False)
```

## Architecture: Relational domain model

**Models -> Relationships -> Database Schema**

Each model maps to a database table with explicit relationships managed by SQLAlchemy.

## Domain entity matrix

| Model        | Primary Purpose                                  | Key Fields                                                          | Unique Constraints |
| ------------ | ------------------------------------------------ | ------------------------------------------------------------------- | ------------------ |
| **User**     | Authentication and identity                      | username                                                            | username, email    |
| **Post**     | Polymorphic base for kind-discriminated posts (joined-table inheritance) | owner_id (FK), kind (`client_referral` \| `provider_availability`, CHECK-constrained) | —                  |
| **ClientReferral**       | Per-kind child table for `Post.kind == 'client_referral'` (no PII). Mirrors the multi-section intake form (Client Location / Demographics / Description / Services / Insurance). | id (PK + FK to `posts.id`, cascade delete); **Location**: location_city / location_state (CHECK in `US_STATES`) / location_zip (TEXT NOT NULL) / location_in_person, location_virtual (CHECK in `LOCATION_AVAILABILITY_OPTIONS`) / desired_times (JSON NOT NULL — list of `<day>_<slot>` tokens from `DESIRED_TIME_SLOTS`); **Demographics**: client_dem_ages (CHECK in `CLIENT_AGE_GROUPS`) / language_preferred (CHECK in `LANGUAGE_PREFERRED_OPTIONS`); **Description**: description (TEXT NOT NULL); **Services**: services (JSON NOT NULL — list of tokens from `CLIENT_REFERRAL_SERVICES`) / services_psychotherapy_modality (TEXT NULL); **Insurance**: insurance (CHECK in `INSURANCE_OPTIONS`) | —                  |
| **ProviderAvailability** | Per-kind child table for `Post.kind == 'provider_availability'` (no PII). Mirrors the multi-section intake form (Provider Information / Location / Availability / Featured Services / Insurance). | id (PK + FK to `posts.id`, cascade delete); **Provider Information**: practice_name / available_providers (TEXT NOT NULL); **Location**: location_city / location_state (CHECK in `US_STATES`) / location_zip (TEXT NOT NULL); **Availability**: in_person_sessions, virtual_sessions (CHECK in `LOCATION_AVAILABILITY_OPTIONS`) / desired_times (JSON NOT NULL — list of `<day>_<slot>` tokens from `DESIRED_TIME_SLOTS`); **Featured Services**: services (JSON NOT NULL — list of tokens from `CLIENT_REFERRAL_SERVICES`, schema enforces non-empty) / treatment_modality (TEXT NULL) / settings (JSON NOT NULL — list of tokens from `TREATMENT_SETTINGS`, schema enforces non-empty) / client_focus (TEXT NOT NULL) / age_group (CHECK in `CLIENT_AGE_GROUPS`) / non_english_services (CHECK in `LANGUAGE_PREFERRED_OPTIONS`); **Insurance**: payment_situation (CHECK in `INSURANCE_OPTIONS`) / sliding_scale (BOOL NOT NULL) / cost (TEXT NULL) | —                  |
| **AuditLog** | Append-only mutation record (RESOURCE_GRAMMAR.md:135) | actor_id (FK, SET NULL), resource_type, resource_id, action, before/after (JSON) | —                  |

## Directory structure

**Core model files:**

- `user.py` - User authentication and profile (extends FastAPI Users)
- `post.py` - Polymorphic `Post` base + `ClientReferral` and `ProviderAvailability` JTI subclasses. `Post` holds the shared header (owner, timestamps, `kind` discriminator, `posts_kind_check` CHECK constraint); each subclass owns a child table keyed by `id` FK to `posts.id` with `ON DELETE CASCADE`. Adding a new kind = a new subclass + child table + an entry in `POST_KINDS` (the CHECK constraint reads it). The allowed-values tuples (`US_STATES`, `LOCATION_AVAILABILITY_OPTIONS`, `CLIENT_AGE_GROUPS`, `LANGUAGE_PREFERRED_OPTIONS`, `CLIENT_REFERRAL_SERVICES`, `INSURANCE_OPTIONS`, `TREATMENT_SETTINGS`, `DESIRED_TIME_SLOTS`) are the source of truth — both kinds share them where the form vocabulary overlaps. The SQLAlchemy CHECK constraints render from these tuples, and a guardrail test (`src/schemas/test_post.py::test_schema_literals_match_model_tuples`) keeps the schema's `Literal[...]` lists aligned.

**Infrastructure:**

- `base.py` - BaseModel with common fields (id, timestamps, soft deletion)
- `__init__.py` - Model exports and package configuration

## Implementation patterns

### Creating a new model

1. **Define the model** in `[entity].py`:

```python
from sqlalchemy import Column, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.types import Uuid
from .base import BaseModel

class NewEntity(BaseModel):
    __tablename__ = "new_entities"

    # Business fields
    name = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    # Foreign key relationships
    owner_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # SQLAlchemy relationships
    owner = relationship("User", back_populates="owned_entities")

    # Database constraints
    __table_args__ = (
        UniqueConstraint("name", "owner_id", name="uq_entity_name_per_owner"),
    )
```

2. **Add to model exports** in `__init__.py`:

```python
from .new_entity import NewEntity

__all__ = [
    "BaseModel",
    "metadata",
    "User",
    "NewEntity",  # Add new model
]
```

3. **Create migration** using Alembic:

```bash
alembic revision --autogenerate -m "Add new_entity table"
alembic upgrade head
```

### Basemodel inheritance pattern

All models inherit from `BaseModel` for consistent structure:

```python
class BaseModel(declarative_base()):
    __abstract__ = True

    # UUID primary key
    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Automatic audit timestamps
    @declared_attr
    def created_at(cls):
        return Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    @declared_attr
    def updated_at(cls):
        return Column(DateTime(timezone=True), nullable=False,
                     server_default=func.now(), onupdate=func.now())

    # Soft deletion support
    @declared_attr
    def deleted_at(cls):
        return Column(DateTime(timezone=True), nullable=True)
```

### Relationship definition pattern

When adding relationships between models, use explicit foreign_keys and back_populates for clarity:

```python
class User(BaseModel):
    # One-to-many: User owns many entities
    owned_entities = relationship(
        "NewEntity",
        back_populates="owner",
        foreign_keys="NewEntity.owner_id"
    )

class NewEntity(BaseModel):
    owner_id = Column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Many-to-one: Entity belongs to one owner
    owner = relationship(
        "User",
        back_populates="owned_entities",
        foreign_keys=[owner_id]
    )
```

### Database constraint patterns

Use SQLAlchemy constraints for data integrity:

```python
class NewEntity(BaseModel):
    # Ensure unique name per owner
    __table_args__ = (
        UniqueConstraint(
            "name", "owner_id",
            name="uq_entity_name_per_owner"
        ),
    )

class User(BaseModel):
    # Ensure unique usernames
    username = Column(Text, unique=True, nullable=False)
```

## Common issues and solutions

### Issue: Circular import dependencies

**Problem**: Models importing each other for type hints causes circular imports

**Solution**: Use string references in relationships and type annotations:

```python
# Bad - direct imports cause circular dependencies
from .user import User

class NewEntity(BaseModel):
    user: User = relationship("User", ...)  # Import required

# Good - string references avoid imports
class NewEntity(BaseModel):
    user = relationship("User", back_populates="entities")  # String reference
```

### Issue: Missing cascade deletes

**Problem**: Deleting parent records leaves orphaned child records

**Solution**: Use appropriate cascade options on relationships:

```python
# Bad - no cascade, orphaned records remain
class User(BaseModel):
    entities = relationship("NewEntity", back_populates="owner")

# Good - cascade deletes child records
class User(BaseModel):
    entities = relationship(
        "NewEntity",
        back_populates="owner",
        cascade="all, delete-orphan"
    )
```

### Issue: Timezone-naive datetime fields

**Problem**: Datetime fields without timezone information cause comparison issues

**Solution**: Always use timezone-aware datetime columns:

```python
# Bad - timezone-naive datetime
class NewEntity(BaseModel):
    happened_at = Column(DateTime, nullable=False)  # No timezone

# Good - timezone-aware datetime
class NewEntity(BaseModel):
    happened_at = Column(DateTime(timezone=True), nullable=False)  # With timezone
```

## Tests

**TODO** — no colocated tests yet. Most model behavior is exercised indirectly through repository and route tests. Add `src/models/test_<model_name>.py` when a model carries non-trivial logic (computed fields, validators, custom `__init__`, etc.) that warrants direct coverage.

When changing a model's schema, generate an Alembic migration as part of the same change — see [`../../CLAUDE.md`](../../CLAUDE.md).

## Related documentation

- [Repository Layer](../repositories/README.md) - Data access patterns that work with these models
- [Services Layer](../services/README.md) - Business logic that operates on these domain entities
- [Schemas Layer](../schemas/README.md) - Request/response validation for these models
- [Main Architecture](../README.md) - How models fit into the overall application architecture
