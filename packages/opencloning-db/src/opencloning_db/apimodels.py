"""Shared Pydantic request/response models for the API."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

import opencloning_linkml.datamodel.models as opencloning_models
from opencloning_db.models import SequenceType, Sequence, Primer, Line, SequenceInLine


class ApiModel(BaseModel):
    """Reject unknown JSON keys on all API request/response models in this module."""

    model_config = ConfigDict(extra='forbid')


# --- Auth (OAuth2 password + JWT) ---
class Token(ApiModel):
    access_token: str
    token_type: str = 'bearer'


class UserPublic(ApiModel):
    id: int
    email: str
    display_name: str | None
    is_instance_admin: bool


class UserRef(ApiModel):
    """Minimal user reference for embedding in resource responses."""

    id: int
    display_name: str | None


class WorkspaceRef(ApiModel):
    id: int
    name: str
    role: str


class WorkspaceCreate(ApiModel):
    name: str = Field(min_length=1)


class WorkspaceRename(ApiModel):
    name: str = Field(min_length=1)


class RegisterBody(ApiModel):
    email: EmailStr
    password: str = Field(min_length=1)
    display_name: str | None = None


# --- Sequence sample ---
class SequenceSampleCreate(ApiModel):
    uid: str
    sequence_id: int


class SequenceSampleUpdate(ApiModel):
    sequence_id: int


class SequenceSampleRead(ApiModel):
    id: int
    uid: str
    sequence_id: int


class SequenceSampleCreated(ApiModel):
    id: int
    uid: str


# --- Tags ---
class TagCreate(ApiModel):
    name: str = Field(min_length=1)

    @field_validator('name', mode='before')
    @classmethod
    def strip_tag_name(cls, v: object) -> object:
        # We do it before to strip before counting the length of the string
        if isinstance(v, str):
            return v.strip()
        return v


class TagRead(ApiModel):
    id: int
    name: str


class EntityTagAttach(ApiModel):
    tag_id: int


# --- Entity refs ---
class InputEntityRef(ApiModel):
    id: int
    type: str
    name: str | None


class SequencingFileRef(ApiModel):
    id: int
    original_name: str


# --- Common responses ---
class IdResponse(ApiModel):
    id: int


class RemovedResponse(ApiModel):
    removed: int


class DeletedResponse(ApiModel):
    deleted: int
    data: dict | None = None


# --- Cloning strategy ---
class CloningStrategyIdMapping(ApiModel):
    localId: int
    databaseId: int


class CloningStrategyResponse(ApiModel):
    id: int
    mappings: list[CloningStrategyIdMapping]


# --- Sequence / primer refs ---
class SequenceRef(ApiModel):
    id: int
    name: str | None
    sequence_type: SequenceType
    tags: list[TagRead] = []
    sample_uids: list[str] = []
    seguid: str | None = None
    created_at: datetime
    created_by: UserRef | None = None


class SequenceUpdate(ApiModel):
    name: str | None = None
    sequence_type: SequenceType | None = None


class PrimerUpdate(ApiModel):
    name: str | None = None
    uid: str | None = None

    @field_validator('uid', mode='before')
    @classmethod
    def strip_uid(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator('name', mode='before')
    @classmethod
    def strip_name(cls, v: object) -> object:
        if isinstance(v, str):
            stripped_name = v.strip()
            if len(stripped_name) < 2:
                raise ValueError('Primer name must be at least 2 characters long')
            return stripped_name
        return v


class PrimerCreate(ApiModel):
    name: str
    uid: str | None = None
    sequence: str = Field(min_length=2, pattern=r'^[ACGTacgt]+$')


class PrimerBulkSubmission(ApiModel):
    name: str
    uid: str | None = None
    sequence: str


class PrimerBulkRow(PrimerBulkSubmission):
    sequence_invalid: bool
    name_exists: bool
    sequence_exists: bool
    uid_exists: bool
    name_duplicated: bool
    sequence_duplicated: bool
    uid_duplicated: bool


class PrimerRef(ApiModel):
    id: int
    name: str | None
    sequence: str
    uid: str | None = None
    tags: list[TagRead] = []
    created_at: datetime
    created_by: UserRef | None = None


class SequenceSampleWithSequence(ApiModel):
    id: int
    uid: str
    sequence_id: int
    sequence: SequenceRef


# --- Line ---
class SequenceInLineRef(ApiModel):
    """Sequence in a line, including the SequenceInLine instance id."""

    id: int
    sequence: SequenceRef


class LineRef(ApiModel):
    id: int
    uid: str
    sequences_in_line: list[SequenceInLineRef]
    parent_ids: list[int]
    tags: list[TagRead]
    created_at: datetime
    created_by: UserRef | None = None


class LineCreate(ApiModel):
    uid: str
    allele_ids: list[int] = []
    plasmid_ids: list[int] = []
    parent_ids: list[int] = []


class LineUpdate(ApiModel):
    uid: str | None = None
    allele_ids: list[int] | None = None
    plasmid_ids: list[int] | None = None
    parent_ids: list[int] | None = None


def _user_ref(user) -> UserRef | None:
    if user is None:
        return None
    return UserRef(id=user.id, display_name=user.display_name)


def sequence_ref(sequence: Sequence) -> SequenceRef:
    return SequenceRef(
        id=sequence.id,
        name=sequence.name,
        sequence_type=sequence.sequence_type,
        tags=[TagRead(id=t.id, name=t.name) for t in sequence.tags],
        sample_uids=sequence.sample_uids,
        seguid=sequence.seguid,
        created_at=sequence.created_at,
        created_by=_user_ref(sequence.created_by),
    )


def primer_ref(primer: Primer) -> PrimerRef:
    return PrimerRef(
        id=primer.id,
        name=primer.name,
        sequence=primer.sequence,
        uid=primer.uid,
        tags=[TagRead(id=t.id, name=t.name) for t in primer.tags],
        created_at=primer.created_at,
        created_by=_user_ref(primer.created_by),
    )


def sequence_in_line_ref(sil: SequenceInLine) -> SequenceInLineRef:
    """Build a SequenceInLineRef from a SequenceInLine ORM instance."""
    seq = sil.sequence
    return SequenceInLineRef(
        id=sil.id,
        sequence=sequence_ref(seq),
    )


def line_ref(line: Line) -> LineRef:
    return LineRef(
        id=line.id,
        uid=line.uid,
        sequences_in_line=[sequence_in_line_ref(sil) for sil in line.sequences_in_line],
        parent_ids=line.parent_ids,
        tags=[TagRead(id=tag.id, name=tag.name) for tag in line.tags],
        created_at=line.created_at,
        created_by=_user_ref(line.created_by),
    )


class SequenceSearchResult(ApiModel):
    sequence_ref: SequenceRef
    sequence: opencloning_models.TextFileSequence
    shift: int = 0
    reverse_complemented: bool = False


class SequenceValidationRow(ApiModel):
    file_name: str
    reading_error: bool

    name: str | None = None
    length: int | None = None
    circular: bool | None = None
    seguid: str | None = None
    circularised_seguid: str | None = None

    sequence_exists: bool | None = None
    sequence_circularised_exists: bool | None = None
    name_exists: bool | None = None

    duplicated_seguid: bool | None = None
    duplicated_name: bool | None = None
