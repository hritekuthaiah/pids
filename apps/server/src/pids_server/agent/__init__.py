"""LLM agent layer (AIL-06/07/08, ADR-0007): triage, procedure retrieval, event-log queries.

Off the alerting path by construction: alerts are raised by the decision core whether or
not an LLM is reachable. Tools are read-only; recommendations are proposals an operator
approves or rejects one by one.
"""
