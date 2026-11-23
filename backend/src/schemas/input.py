from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from src.constants.labels import Band, Control, HVAC, Position, Predictor

Title = Annotated[str, StringConstraints(min_length=1, max_length=80)]
Note = Annotated[str, StringConstraints(max_length=350)]


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True, allow_inf_nan=False)


class Login(Input):
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=128)


class Session(Input):
    code: str = Field(pattern=r'^[A-Z0-9][A-Z0-9-]{0,23}$')
    title: Title
    recorded_on: date = Field(ge=date(2000, 1, 1), le=date(2100, 12, 31))
    start_time: str = Field(pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    band: Band
    room: str = Field(min_length=1, max_length=48)
    note: Note = ''


class Reading(Input):
    session_id: int = Field(gt=0)
    reference: str = Field(min_length=1, max_length=64)
    hvac: HVAC
    position: Position
    traffic: int = Field(ge=0, le=1000)
    noise: float = Field(ge=0, le=140, multiple_of=0.01)
    note: Note = ''


class Method(Input):
    version: str = Field(pattern=r'^[A-Z0-9][A-Z0-9.-]{0,31}$')
    title: Title
    predictor: Predictor
    controls: list[Control] = Field(max_length=4)
    note: Note = ''

    @model_validator(mode='after')
    def check_controls(self):
        if len(set(self.controls)) != len(self.controls):
            raise ValueError('控制量不可重复')
        if self.predictor in self.controls:
            raise ValueError('不能同时作为解释量和控制量')
        return self


class Diagnostic(Input):
    title: Title
    method_id: int = Field(gt=0)
    session_ids: list[int] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def unique_sessions(self):
        if min(self.session_ids) < 1 or len(set(self.session_ids)) != len(self.session_ids):
            raise ValueError('时段编号必须为正整数，且不可重复')
        return self


class IntakeMethod(Input):
    """Variable definition carried by the incoming diagnostic. Unknown extra keys are kept with the original."""

    model_config = ConfigDict(extra='allow', str_strip_whitespace=True, allow_inf_nan=False)

    version: str = Field(pattern=r'^[A-Z0-9][A-Z0-9.-]{0,31}$')
    predictor: Predictor
    controls: list[Control] = Field(max_length=4)

    @model_validator(mode='after')
    def check_controls(self):
        if len(set(self.controls)) != len(self.controls):
            raise ValueError('来件控制量不可重复')
        if self.predictor in self.controls:
            raise ValueError('来件解释量不能同时作为控制量')
        return self


class IntakeClaim(Input):
    model_config = ConfigDict(extra='allow', str_strip_whitespace=True, allow_inf_nan=False)

    n: int | None = Field(default=None, ge=0, le=4000)
    raw: float = Field(ge=-1, le=1)
    partial: float = Field(ge=-1, le=1)


class IntakeReading(Input):
    """A paired sample. Rows missing an input are still retained and counted as missing samples."""

    model_config = ConfigDict(extra='allow', str_strip_whitespace=True, allow_inf_nan=False)

    session: str | None = Field(default=None, max_length=24)
    reference: str | None = Field(default=None, max_length=64)
    band: Band | None = None
    hvac: HVAC | None = None
    position: Position | None = None
    traffic: int | None = Field(default=None, ge=0, le=1000)
    noise: float | None = Field(default=None, ge=0, le=140)


def _envelope(raw):
    """Accept either the compact hand-off format or a full diagnostic export from the other studio."""
    if not isinstance(raw, dict):
        return raw
    data = dict(raw)
    snapshot = data.get('snapshot') if isinstance(data.get('snapshot'), dict) else {}
    if not data.get('method') and snapshot.get('method'):
        data['method'] = snapshot['method']
    if not data.get('algorithm') and snapshot.get('algorithm'):
        data['algorithm'] = snapshot['algorithm']
    if 'readings' not in data:
        data['readings'] = snapshot.get('readings', [])
    if not data.get('claim') and isinstance(data.get('result'), dict):
        result = data['result']
        if result.get('raw') is not None and result.get('partial') is not None:
            data['claim'] = {'n': result.get('n'), 'raw': result['raw'], 'partial': result['partial']}
    if data.get('method') is None:
        data.pop('method', None)
    if data.get('claim') is None:
        data.pop('claim', None)
    readings = data.get('readings')
    if readings is None:
        data['readings'] = []
    elif isinstance(readings, list):
        data['readings'] = [_reading_envelope(row) for row in readings]
    return data


def _reading_envelope(row):
    if not isinstance(row, dict):
        return row
    data = dict(row)
    if data.get('session') is None:
        if data.get('code') is not None:
            data['session'] = data['code']
        elif data.get('session_id') is not None:
            data['session'] = str(data['session_id'])
    if isinstance(data.get('session'), str):
        data['session'] = data['session'].strip() or None
    return data


class Intake(Input):
    """Envelope for another studio's diagnostic. Legacy documents may omit parts we cannot use,
    so the original is always retained even when it cannot be recalculated."""

    model_config = ConfigDict(extra='allow', str_strip_whitespace=True, allow_inf_nan=False)

    intake_key: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')
    source_studio: str = Field(min_length=1, max_length=48)
    title: Title
    method: IntakeMethod | None = None
    algorithm: str | None = Field(default=None, max_length=48)
    claim: IntakeClaim | None = None
    readings: list[IntakeReading] = Field(default_factory=list, max_length=4000)

    @model_validator(mode='before')
    @classmethod
    def recognise_export(cls, data):
        return _envelope(data)

    @model_validator(mode='after')
    def unique_samples(self):
        keys = [(row.session, row.reference) for row in self.readings
                if row.session is not None and row.reference is not None]
        if len(set(keys)) != len(keys):
            raise ValueError('来件内同一时段的声测编号不可重复')
        return self


class Decision(Input):
    text: str = Field(min_length=8, max_length=500)
