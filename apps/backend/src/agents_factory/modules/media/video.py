from agents_factory.modules.media.contracts import NormalizedMediaObservation


def normalize_video(*, media_type: str, byte_size: int) -> NormalizedMediaObservation:
    return NormalizedMediaObservation(
        kind="video",
        status="HUMAN_REVIEW",
        fields={
            "media_type": media_type,
            "byte_size": byte_size,
            "advanced_analysis": False,
        },
        reason_code="video_human_review_required",
    )
