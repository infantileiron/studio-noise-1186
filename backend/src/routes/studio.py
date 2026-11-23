from fastapi import APIRouter, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from src.controllers.accounts import Reader, Reviewer, Writer, login
from src.schemas import input as forms
from src.services import catalog, diagnostics, intakes

router = APIRouter()


@router.post('/auth/login')
def sign_in(data: forms.Login):
    return login(data)


@router.get('/auth/me')
def identity(account: Reader):
    return account


@router.get('/sessions')
def list_sessions(_: Reader):
    return catalog.sessions()


@router.post('/sessions', status_code=201)
def create_session(data: forms.Session, account: Writer):
    return catalog.add_session(data.model_dump(mode='json'), account)


@router.get('/readings')
def list_readings(_: Reader, session_id: int | None = None):
    return catalog.readings(session_id)


@router.post('/readings', status_code=201)
def create_reading(data: forms.Reading, account: Writer):
    return catalog.add_reading(data.model_dump(mode='json'), account)


@router.get('/methods')
def list_methods(_: Reader):
    return catalog.methods()


@router.post('/methods', status_code=201)
def create_method(data: forms.Method, account: Writer):
    return catalog.add_method(data.model_dump(mode='json'), account)


@router.get('/diagnostics')
def list_diagnostics(account: Reader):
    return diagnostics.list_runs(account)


@router.post('/diagnostics', status_code=202)
def queue_diagnostic(data: forms.Diagnostic, account: Writer):
    return diagnostics.queue(data.model_dump(), account)


@router.get('/diagnostics/{identifier}')
def diagnostic(identifier: int, account: Reader):
    return diagnostics.get_run(identifier, account)


@router.post('/diagnostics/{identifier}/publish')
def publish_diagnostic(identifier: int, data: forms.Decision, account: Reviewer):
    return diagnostics.publish(identifier, data.text, account)


@router.get('/diagnostics/{identifier}/export')
def download(identifier: int, account: Reader):
    filename, document = diagnostics.export(identifier, account)
    return Response(document, media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})


@router.get('/intakes')
def list_intakes(account: Reader):
    return intakes.list_intakes(account)


@router.post('/intakes', status_code=201)
def submit_intake(data: forms.Intake, account: Writer):
    run, inserted = intakes.submit(data, account)
    summary = {key: value for key, value in intakes.serialise(run).items()
               if key not in ('original', 'result', 'evidence')}
    return JSONResponse(jsonable_encoder(summary), status_code=201 if inserted else 200)


@router.get('/intakes/{identifier}')
def intake(identifier: int, account: Reader):
    return intakes.serialise(intakes.get_intake(identifier, account))


@router.post('/intakes/{identifier}/retry', status_code=202)
def retry_intake(identifier: int, account: Writer):
    return intakes.serialise(intakes.retry(identifier, account))


@router.post('/intakes/{identifier}/retest')
def publish_retest(identifier: int, data: forms.Decision, account: Reviewer):
    return intakes.serialise(intakes.publish_retest(identifier, data.text, account))


@router.get('/intakes/{identifier}/export')
def download_intake(identifier: int, account: Reader):
    filename, document = intakes.export(identifier, account)
    return Response(document, media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename="{filename}"'})
