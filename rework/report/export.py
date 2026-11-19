from .snapshot import ReportSnapshot, encode_snapshot


def export_report(snapshot: ReportSnapshot) -> bytes:
    return (encode_snapshot(snapshot) + '\n').encode('utf-8')
