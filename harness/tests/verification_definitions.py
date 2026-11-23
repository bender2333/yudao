# 测试使用真实定义的解析和校验；两个核验角色只通过数据接入。
from copy import deepcopy

from harness.definitions import DEFINITIONS, Definitions, definitions_from_contents


INSPECTOR = "inspection"


def with_second_delivery_verifier() -> Definitions:
    contents = deepcopy(DEFINITIONS.contents)
    organization = contents["organization.json"]
    quality = next(role for role in organization["departments"] if role["id"] == "quality")
    organization["departments"].append({**quality, "id": INSPECTOR, "roles": [INSPECTOR], "label": "复核"})
    verification = organization["verification"]
    verification["verifiers"].append({**verification["verifiers"][0], "role": INSPECTOR})
    verification["write_scopes"][INSPECTOR] = verification["write_scopes"]["quality"]
    contents["roles.json"][INSPECTOR] = contents["roles.json"]["quality"]
    contracts = contents["proposal_contracts.json"]["roles"]
    contracts[INSPECTOR] = contracts["quality"]
    for work in contents["work_items.json"]["kinds"].values():
        if "quality" in work.get("departments", {}):
            work["departments"][INSPECTOR] = work["departments"]["quality"]
    contents["routings.json"]["routings"][0]["departments"].append(INSPECTOR)
    return definitions_from_contents(contents)
