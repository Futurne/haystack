from typing import List, Tuple, Dict, Any

from haystack.database.base import Label


def calculate_reader_metrics(metric_counts: Dict[str, float], correct_retrievals: int):
    number_of_has_answer = correct_retrievals - metric_counts["number_of_no_answer"]

    metrics = {
        "reader_top1_accuracy" : metric_counts["correct_readings_top1"] / correct_retrievals,
        "reader_top1_accuracy_has_answer" : metric_counts["correct_readings_top1_has_answer"] / number_of_has_answer,
        "reader_top_k_accuracy" : metric_counts["correct_readings_topk"] / correct_retrievals,
        "reader_topk_accuracy_has_answer" : metric_counts["correct_readings_topk_has_answer"] / number_of_has_answer,
        "reader_top1_em" : metric_counts["exact_matches_top1"] / correct_retrievals,
        "reader_top1_em_has_answer" : metric_counts["exact_matches_top1_has_answer"] / number_of_has_answer,
        "reader_topk_em" : metric_counts["exact_matches_topk"] / correct_retrievals,
        "reader_topk_em_has_answer" : metric_counts["exact_matches_topk_has_answer"] / number_of_has_answer,
        "reader_top1_f1" : metric_counts["summed_f1_top1"] / correct_retrievals,
        "reader_top1_f1_has_answer" : metric_counts["summed_f1_top1_has_answer"] / number_of_has_answer,
        "reader_topk_f1" : metric_counts["summed_f1_topk"] / correct_retrievals,
        "reader_topk_f1_has_answer" : metric_counts["summed_f1_topk_has_answer"] / number_of_has_answer,
    }

    if metric_counts["number_of_no_answer"]:
        metrics["reader_top1_no_answer_accuracy"] = metric_counts["correct_no_answers_top1"] / metric_counts[
            "number_of_no_answer"]
        metrics["reader_topk_no_answer_accuracy"] = metric_counts["correct_no_answers_topk"] / metric_counts[
            "number_of_no_answer"]
    else:
        metrics["reader_top1_no_answer_accuracy"] = None  # type: ignore
        metrics["reader_topk_no_answer_accuracy"] = None  # type: ignore

    return metrics


def calculate_average_precision(questions_with_docs: List[dict]):
    questions_with_correct_doc = []
    summed_avg_precision_retriever = 0.0

    for question in questions_with_docs:
        for doc_idx, doc in enumerate(question["docs"]):
            # check if correct doc among retrieved docs
            if doc.id == question["question"].document_id:
                summed_avg_precision_retriever += 1 / (doc_idx + 1)
                questions_with_correct_doc.append({
                    "question": question["question"],
                    "docs": question["docs"]
                })
                break

    return questions_with_correct_doc, summed_avg_precision_retriever


def eval_counts_reader(question: Label, predicted_answers: Dict[str, Any], metric_counts: Dict[str, float]):
    # Calculates evaluation metrics for one question and adds results to counter.
    # check if question is answerable
    if not question.no_answer:
        for answer_idx, answer in enumerate(predicted_answers["answers"]):
            found_answer = False
            found_em = False
            best_f1 = 0
            if answer["document_id"] == question.document_id:
                gold_spans = [(question.offset_start_in_doc, question.offset_start_in_doc + len(question.answer))]  # type: ignore
                predicted_span = (answer["offset_start_in_doc"], answer["offset_end_in_doc"])

                for gold_span in gold_spans:
                    # check if overlap between gold answer and predicted answer
                    if not found_answer:
                        metric_counts, found_answer = _count_overlap(gold_span, predicted_span, metric_counts, answer_idx)  # type: ignore

                    # check for exact match
                    if not found_em:
                        metric_counts, found_em = _count_exact_match(gold_span, predicted_span, metric_counts, answer_idx)  # type: ignore

                    # calculate f1
                    current_f1 = _calculate_f1(gold_span, predicted_span)  # type: ignore
                    # top-1 answer
                    if answer_idx == 0:
                        metric_counts["summed_f1_top1"] += current_f1
                        metric_counts["summed_f1_top1_has_answer"] += current_f1
                    if current_f1 > best_f1:
                        best_f1 = current_f1
                # top-k answers: use best f1-score
                metric_counts["summed_f1_topk"] += best_f1
                metric_counts["summed_f1_topk_has_answer"] += best_f1

            if found_em:
                break

    # question not answerable
    else:
        metric_counts["number_of_no_answer"] += 1
        metric_counts = _count_no_answer(predicted_answers["answers"], metric_counts)

    return metric_counts


def eval_counts_reader_batch(pred: Dict[str, Any], metric_counts: Dict[str, float]):
    # Calculates evaluation metrics for one question and returns adds results to counter.

    # check if question in answerable
    if not pred["label"].no_answer:
        for answer_idx, answer in enumerate(pred["answers"]):
            found_answer = False
            found_em = False
            best_f1 = 0
            # check if correct document:
            if answer["document_id"] == pred["label"].document_id:
                gold_spans = [(pred["label"].offset_start_in_doc, pred["label"].offset_start_in_doc + len(pred["label"].answer))]
                predicted_span = (answer["offset_start_in_doc"], answer["offset_end_in_doc"])

                for gold_span in gold_spans:
                    # check if overlap between gold answer and predicted answer
                    if not found_answer:
                        metric_counts, found_answer = _count_overlap(
                            gold_span, predicted_span, metric_counts, answer_idx
                        )
                    # check for exact match
                    if not found_em:
                        metric_counts, found_em = _count_exact_match(
                            gold_span, predicted_span, metric_counts, answer_idx
                        )
                    # calculate f1
                    current_f1 = _calculate_f1(gold_span, predicted_span)
                    # top-1 answer
                    if answer_idx == 0:
                        metric_counts["summed_f1_top1"] += current_f1
                        metric_counts["summed_f1_top1_has_answer"] += current_f1
                    if current_f1 > best_f1:
                        best_f1 = current_f1
                    # top-k answers: use best f1-score
                metric_counts["summed_f1_topk"] += best_f1
                metric_counts["summed_f1_topk_has_answer"] += best_f1
    # question not answerable
    else:
        metric_counts["number_of_no_answer"] += 1
        metric_counts = _count_no_answer(pred["answers"], metric_counts)

    return metric_counts


def _count_overlap(
    gold_span: Tuple[int, int],
    predicted_span: Tuple[int, int],
    metric_counts: Dict[str, float],
    answer_idx: int
    ):
    # Checks if overlap between prediction and real answer.

    found_answer = False

    if (gold_span[0] <= predicted_span[1]) and (predicted_span[0] <= gold_span[1]):
        # top-1 answer
        if answer_idx == 0:
            metric_counts["correct_readings_top1"] += 1
            metric_counts["correct_readings_top1_has_answer"] += 1
        # top-k answers
        metric_counts["correct_readings_topk"] += 1
        metric_counts["correct_readings_topk_has_answer"] += 1
        found_answer = True

    return metric_counts, found_answer


def _count_exact_match(
    gold_span: Tuple[int, int],
    predicted_span: Tuple[int, int],
    metric_counts: Dict[str, float],
    answer_idx: int
    ):
    # Check if exact match between prediction and real answer.
    # As evaluation needs to be framework independent, we cannot use the farm.evaluation.metrics.py functions.

    found_em = False

    if (gold_span[0] == predicted_span[0]) and (gold_span[1] == predicted_span[1]):
        # top-1 answer
        if answer_idx == 0:
            metric_counts["exact_matches_top1"] += 1
            metric_counts["exact_matches_top1_has_answer"] += 1
        # top-k answers
        metric_counts["exact_matches_topk"] += 1
        metric_counts["exact_matches_topk_has_answer"] += 1
        found_em = True

    return metric_counts, found_em


def _calculate_f1(gold_span: Tuple[int, int], predicted_span: Tuple[int, int]):
    # Calculates F1-Score for prediction based on real answer.
    # As evaluation needs to be framework independent, we cannot use the farm.evaluation.metrics.py functions.

    pred_indices = list(range(predicted_span[0], predicted_span[1] + 1))
    gold_indices = list(range(gold_span[0], gold_span[1] + 1))
    n_overlap = len([x for x in pred_indices if x in gold_indices])
    if pred_indices and gold_indices and n_overlap:
        precision = n_overlap / len(pred_indices)
        recall = n_overlap / len(gold_indices)
        f1 = (2 * precision * recall) / (precision + recall)

        return f1
    else:
        return 0


def _count_no_answer(answers: List[dict], metric_counts: Dict[str, float]):
    # Checks if one of the answers is 'no answer'.

    for answer_idx, answer in enumerate(answers):
        # check if 'no answer'
        if answer["answer"] is None:
            # top-1 answer
            if answer_idx == 0:
                metric_counts["correct_no_answers_top1"] += 1
                metric_counts["correct_readings_top1"] += 1
                metric_counts["exact_matches_top1"] += 1
                metric_counts["summed_f1_top1"] += 1
            # top-k answers
            metric_counts["correct_no_answers_topk"] += 1
            metric_counts["correct_readings_topk"] += 1
            metric_counts["exact_matches_topk"] += 1
            metric_counts["summed_f1_topk"] += 1
            break

    return metric_counts