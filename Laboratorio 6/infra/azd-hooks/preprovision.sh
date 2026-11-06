#!/bin/sh
# Registra los proveedores de recursos que usa la plantilla (en una suscripcion nueva vienen sin registrar).
# La plantilla original registraba funciones en vista previa de AKS que ya no hacen falta.
echo "Registrando proveedores de recursos de Azure"
for proveedor in Microsoft.ContainerService Microsoft.ContainerRegistry Microsoft.Dashboard Microsoft.Monitor \
                 Microsoft.AlertsManagement Microsoft.OperationalInsights Microsoft.Insights; do
  az provider register --namespace "$proveedor" --wait
  echo "  $proveedor: $(az provider show --namespace "$proveedor" --query registrationState -o tsv)"
done
