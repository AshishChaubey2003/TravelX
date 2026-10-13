from rest_framework import serializers


class PlanTripRequestSerializer(serializers.Serializer):
    """Validates POST /api/v1/ai/plan/ input (F-22 Phase 2.1).

    - query: required, must be a genuine string, non-blank after trimming,
      capped at 500 characters. Lists/dicts/numbers/bools are rejected
      rather than silently stringified.
    - session: optional dict carrying the client-side step-machine state.
    """
    query = serializers.CharField(max_length=500, allow_blank=False)
    session = serializers.DictField(required=False, default=dict)

    def validate_query(self, value):
        raw = self.initial_data.get('query')
        if not isinstance(raw, str):
            raise serializers.ValidationError('Query must be a string.')
        return value