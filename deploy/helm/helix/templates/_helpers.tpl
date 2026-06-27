{{- define "helix.name" -}}helix{{- end -}}
{{- define "helix.fullname" -}}{{ .Release.Name }}-helix{{- end -}}
{{- define "helix.labels" -}}
app.kubernetes.io/name: {{ include "helix.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
{{- define "helix.selectorLabels" -}}
app.kubernetes.io/name: {{ include "helix.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
