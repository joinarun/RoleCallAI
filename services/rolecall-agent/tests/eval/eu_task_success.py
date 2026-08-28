from tests.eval.eu_judge import evaluate_component


def evaluate(instance):
    return evaluate_component(instance, "task_success")
