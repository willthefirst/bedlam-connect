# Schemas: Request/response validation and serialization

The `schemas/` directory contains **Pydantic schemas** that define the structure and validation rules for API requests and responses, providing type safety, automatic serialization, and comprehensive validation.

## Core philosophy: Type-safe API contracts

Schemas serve as **API contracts** that ensure data consistency between clients and the server while providing automatic validation, serialization, and comprehensive error messages for invalid data.

### What we do

- **Request validation**: Validate incoming API data with clear error messages
- **Response serialization**: Convert database models to JSON with proper field selection
- **Type safety**: Provide full type annotations for IDE support and runtime validation
- **Configuration**: Use Pydantic's ConfigDict for ORM integration and serialization control

**Example**: Schema with ORM integration:

```python
class UserRead(schemas.BaseUser):
    username: str

    model_config = ConfigDict(from_attributes=True)  # ORM integration
```

### What we don't do

- **Business logic**: Schemas only define structure and basic validation, no business rules
- **Database operations**: Schemas don't interact with databases directly
- **Complex computed fields**: Keep schemas focused on data structure
- **Authentication logic**: Authentication concerns stay in auth layer

**Example**: Don't implement business logic in schemas:

```python
# Bad - business logic in schema
class UserCreateRequest(BaseModel):
    username: str

    def validate_user_can_register(self, existing_users):  # Business logic
        if len(existing_users) >= MAX_USERS:
            raise ValueError("Too many users")

# Good - structure and validation only
class UserCreateRequest(BaseModel):
    username: str

    @field_validator('username')
    def validate_username(cls, v):
        if len(v.strip()) == 0:
            raise ValueError('Username cannot be empty')
        return v.strip()
```

## Architecture: Request/response boundary layer

**API Routes -> Schema Validation -> Service Layer -> Schema Serialization -> Response**

Schemas act as the data contract layer between HTTP and business logic.

## Schema organization matrix

| Schema File | Domain    | Responsibilities                             | Schema Types                                             |
| ----------- | --------- | -------------------------------------------- | -------------------------------------------------------- |
| **user.py** | User data | User CRUD plus activation state-axis subresource (extends FastAPI Users) and audit snapshots | UserRead, UserCreate, UserUpdate, UserActivationUpdate, UserAuditSnapshot, UserActivationAuditSnapshot |
| **post.py** | Posts     | Kind-discriminated read/create/update unions + audit snapshot. `PostCreate`, `PostRead`, and `PostUpdate` are `Annotated[Union[..., ...], Field(discriminator="kind")]` over per-kind schemas. `client_referral` mirrors the multi-section intake form (Client Location: city/state/zip/in_person/virtual/desired_times; Demographics: client_dem_ages/language_preferred; Description: description; Services: services/services_psychotherapy_modality; Insurance: insurance). `provider_availability` mirrors its own multi-section form (Provider Information: practice_name/available_providers; Location: city/state/zip; Availability: in_person_sessions/virtual_sessions/desired_times; Featured Services: services [non-empty] / treatment_modality / settings [non-empty] / client_focus / age_group / non_english_services [defaults to "no"]; Insurance: payment_situation / sliding_scale / cost). Each per-kind schema sets `extra="forbid"`; each Update variant rejects no-op PATCHes via a model validator. Per-section enum types are spelled-out `Literal[...]`s; a guardrail test (`test_post.py::test_schema_literals_match_model_tuples`) keeps them in sync with the model-side tuples that feed the DB CHECK constraints. Pydantic's bool coercion (`"true"`/`"false"` → bool) round-trips form radios cleanly. | PostCreate, PostRead, PostUpdate, ClientReferralCreate, ClientReferralRead, ClientReferralUpdate, ProviderAvailabilityCreate, ProviderAvailabilityRead, ProviderAvailabilityUpdate, PostAuditSnapshot |

## Directory structure

**Domain schema files:**

- `user.py` - User schemas extending FastAPI Users base schemas
- `post.py` - Post schemas: discriminated unions (`PostCreate`, `PostRead`, `PostUpdate`) over per-kind schemas (`ClientReferralCreate`/`Read`/`Update`, `ProviderAvailabilityCreate`/`Read`/`Update`), plus `PostAuditSnapshot`. `kind` is the discriminator; per-kind schemas set `extra="forbid"`. Both kinds mirror multi-section intake forms (5 sections each) and reuse the same per-section literal enums (`_State`, `_Availability`, `_AgeGroup`, `_LanguagePreferred`, `_Service`, `_Insurance`, `_TreatmentSetting`, `_DesiredTimeSlot`) wherever the form vocabulary overlaps. JSON list fields use a `BeforeValidator` to coerce the json-enc bare-string edge case into a 1-element list. Section-enum literals are validated against the model-side tuples by `test_schema_literals_match_model_tuples`. Adding a new post kind = new per-kind schemas plus an entry in each Union.

## Implementation patterns

### Creating request/response schema pairs

Most domains have both request (input) and response (output) schemas:

```python
# Request schema - validates incoming data
class [Entity]CreateRequest(BaseModel):
    name: str  # Required field

    @field_validator('name')
    def validate_name_not_empty(cls, v):
        if not v.strip():
            raise ValueError('Name cannot be empty')
        return v.strip()

# Response schema - serializes outgoing data
class [Entity]Response(BaseModel):
    id: UUID
    name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)  # Enable ORM conversion
```

### Orm integration pattern

Use ConfigDict to enable automatic conversion from SQLAlchemy models:

```python
class [Entity]Response(BaseModel):
    id: UUID
    name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

# Usage in routes - automatic conversion
@router.get("/[entities]/{entity_id}")
async def get_entity(entity_id: UUID) -> [Entity]Response:
    entity = await repo.get_by_id(entity_id)
    return [Entity]Response.model_validate(entity)  # Auto-converts from ORM
```

### FastAPI users integration pattern

Extend FastAPI Users schemas for authentication:

```python
from fastapi_users import schemas

class UserRead(schemas.BaseUser):
    username: str  # Add custom fields to base user

class UserCreate(schemas.BaseUserCreate):
    username: str  # Add custom fields to registration

class UserUpdate(schemas.BaseUserUpdate):
    username: str  # Add custom fields to updates
```

## Common schema issues and solutions

### Issue: Missing validation leading to bad data

**Problem**: Invalid data gets through to business logic
**Solution**: Add comprehensive field validation

```python
# Bad - no validation
class [Entity]CreateRequest(BaseModel):
    name: str

# Good - comprehensive validation
class [Entity]CreateRequest(BaseModel):
    name: str

    @field_validator('name')
    def validate_name(cls, v):
        v = v.strip()
        if not v:
            raise ValueError('Name cannot be empty')
        if len(v) > 200:
            raise ValueError('Name too long (max 200 characters)')
        return v
```

### Issue: Inconsistent ORM conversion

**Problem**: Some schemas work with ORM models, others don't
**Solution**: Consistently use ConfigDict(from_attributes=True)

```python
# Bad - missing ORM configuration
class [Entity]Response(BaseModel):
    id: UUID
    name: str
    # Will fail when converting from SQLAlchemy model

# Good - proper ORM integration
class [Entity]Response(BaseModel):
    id: UUID
    name: str

    model_config = ConfigDict(from_attributes=True)
```

### Issue: Exposing internal fields in responses

**Problem**: Response schemas include fields that shouldn't be public
**Solution**: Explicitly define what fields to include/exclude

```python
# Bad - exposing internal fields
class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str
    password_hash: str  # Should not be exposed!

# Good - only expose public fields
class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

## Schema naming conventions

### Consistent naming patterns

```python
# Request schemas - data coming IN
[Domain]CreateRequest
[Domain]UpdateRequest

# Response schemas - data going OUT
[Domain]Response
[Domain]ListResponse

# Enums - controlled vocabularies
[Domain]Status
[Domain]Type
```

### Example naming consistency

```python
# User domain (follows FastAPI users pattern)
UserRead
UserCreate
UserUpdate

# New domain example
[Entity]CreateRequest
[Entity]Response
[Entity]Status  # Enum
```

## Tests

Colocated tests live alongside the schema modules:

- `test_post.py` — exercises the kind-discriminated `PostCreate` and `PostUpdate` unions: dispatch on `kind`, rejection of missing/unknown `kind`, per-kind required fields and validators (both kinds cover all 5 intake-form sections including the JSON multi-selects `desired_times`, `services`, and — for `provider_availability` — `settings`), whitespace stripping, the per-section enums (state/age/availability/insurance/treatment-setting/etc.), 5-digit ZIP validation, multi-select duplicate rejection, the non-empty enforcement on PA's `services` and `settings`, the bool-from-string coercion (PA's `sliding_scale`), at-least-one-field on Update, the `extra="forbid"` boundary on each per-kind schema, and the `test_schema_literals_match_model_tuples` guardrail (keeps schema literals in lock-step with the model tuples that feed the DB CHECK constraints).

Add `src/schemas/test_<schema_name>.py` when a schema has non-trivial validators or computed fields whose behavior isn't obvious from the field definitions.

## Related documentation

- [API Routes](../api/routes/README.md) - API routes that use these schemas for validation
- [Models Layer](../models/README.md) - Database models that schemas serialize
- [API Layer](../api/README.md) - Overall API architecture showing schema role
