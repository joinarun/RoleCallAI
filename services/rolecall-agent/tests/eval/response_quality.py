"""EU-pinned aggregate quality metric for the RoleCallAI evaluation suite."""

from tests.eval.eu_judge import evaluate_component


def evaluate(instance):
    return evaluate_component(instance, "overall")
