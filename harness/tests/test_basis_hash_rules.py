from harness.validation import _basis_hash_errors

# 依据版本声明（工单 #471）：纯函数 _basis_hash_errors 的组合覆盖。正式成果提交时要声明它依据的当前
# 版本，声明缺失、类型不对、与 host 端当前版本不一致时返回指向该字段的错误；与当前版本一致时放行。
# 三种正式成果的声明字段：ProductSpec 修订与 DeliverySpec 共用 basis_product_spec_hash，
# QAReview 用 basis_delivery_spec_hash。

SPEC_FIELD = "basis_product_spec_hash"
DELIVERY_FIELD = "basis_delivery_spec_hash"
CURRENT = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64


def _errors(field, value, current_hash):
    proposal = {} if value is _MISSING else {field: value}
    return _basis_hash_errors(proposal, field, current_hash)


_MISSING = object()


def test_a_missing_declaration_is_an_error_pointing_at_the_field():
    for field in (SPEC_FIELD, DELIVERY_FIELD):
        for current_hash in (None, CURRENT):
            [error] = _errors(field, _MISSING, current_hash)
            assert error.field == field
            assert "required" in error.message


def test_a_non_string_declaration_is_an_error():
    for value in (123, "", "   ", [], {}):
        [error] = _errors(SPEC_FIELD, value, CURRENT)
        assert error.field == SPEC_FIELD
        assert "must be a content hash string or null" in error.message


def test_the_first_artifact_must_declare_a_null_basis():
    # 还没有当前版本：给任何 hash 都拒绝，null 放行
    [error] = _errors(SPEC_FIELD, CURRENT, None)
    assert error.field == SPEC_FIELD
    assert "must be null when no current version exists" in error.message
    assert repr(CURRENT) in error.message
    assert _errors(SPEC_FIELD, None, None) == []


def test_a_declaration_that_matches_the_current_version_passes():
    for field in (SPEC_FIELD, DELIVERY_FIELD):
        assert _errors(field, CURRENT, CURRENT) == []


def test_a_stale_declaration_is_rejected_with_the_current_version():
    for value, current_hash in ((OTHER, CURRENT), (None, CURRENT)):
        [error] = _errors(DELIVERY_FIELD, value, current_hash)
        assert error.field == DELIVERY_FIELD
        assert "current version is" in error.message
        assert repr(CURRENT) in error.message
        if value is not None:
            assert repr(value) in error.message


def test_errors_serialize_to_field_and_message():
    [error] = _errors(SPEC_FIELD, OTHER, CURRENT)
    assert error.to_dict() == {"field": SPEC_FIELD, "message": error.message}
