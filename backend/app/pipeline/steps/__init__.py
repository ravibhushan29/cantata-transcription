from app.models import StepTag
from app.pipeline.base_step import BaseStep
from app.pipeline.steps.auto_qa_invite import StepAutoQaInvite
from app.pipeline.steps.delivery import StepDelivery
from app.pipeline.steps.manual_qa_submit import StepManualQaSubmit
from app.pipeline.steps.stt_callback_ingest import StepSttCallbackIngest
from app.pipeline.steps.stt_submit import StepSttSubmit

STEP_REGISTRY: dict[StepTag, type[BaseStep]] = {
    StepTag.STT_SUBMIT: StepSttSubmit,
    StepTag.STT_CALLBACK_INGEST: StepSttCallbackIngest,
    StepTag.AUTO_QA_INVITE: StepAutoQaInvite,
    StepTag.MANUAL_QA_SUBMIT: StepManualQaSubmit,
    StepTag.DELIVERY: StepDelivery,
}
