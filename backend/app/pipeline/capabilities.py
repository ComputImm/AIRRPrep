

from enum import Enum


class Capability(str, Enum):

    QUALITY = "quality"

    BARCODE = "barcode"

    UMI = "umi"

    GROUPED = "grouped"

    COLLAPSED = "collapsed"

    PAIRED_END = "paired_end"

    PRIMER = "primer"

    PARSED_HEADER = "parsed_header"

    ASSEMBLED = "assembled"

    SPLIT = "split"

    ALIGNED = "aligned"

    CLUSTERED = "clustered"


# pRESTO annotation fields copied by PairSeq (fields_1 / fields_2)
ANNOTATION_FIELD_TO_CAPABILITY: dict[str, Capability] = {
    "BARCODE": Capability.BARCODE,
    "UMI": Capability.UMI,
    "UID": Capability.UMI,
    "PRIMER": Capability.PRIMER,
    "CREGION": Capability.PRIMER,
    "PRCONS": Capability.GROUPED,
    "DUPCOUNT": Capability.GROUPED,
    "CONSCOUNT": Capability.GROUPED,
    "CLUSTER": Capability.CLUSTERED,
}


def capability_for_annotation_field(field: str) -> Capability | None:
    return ANNOTATION_FIELD_TO_CAPABILITY.get(str(field).strip().upper())