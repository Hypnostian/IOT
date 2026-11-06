targetScope = 'subscription'

// Plantilla sabbour/aks-app-template ajustada para una suscripcion Azure for Students
// (ver la seccion "Cambios respecto a la plantilla" del README).

@minLength(1)
@maxLength(64)
@description('Name of the the environment which is used to generate a short unqiue hash used in all resources.')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

@description('Region de Azure Managed Grafana. El servicio no existe en todas las regiones (por ejemplo, Mexico Central).')
param grafanaLocation string = 'westus'

@description('Id of the user or app to assign application roles')
param principalId string = ''

@description('Tipo del principal que recibe el rol Grafana Admin (User si es la persona que ejecuta azd).')
param principalType string = 'User'

@description('The Kubernetes version.')
param kubernetesVersion string = '1.36'

@description('Tamano de los nodos del clúster.')
param nodeVmSize string = 'Standard_B2as_v2'

@description('Cantidad de nodos del clúster.')
param nodeCount int = 2

var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

// Resource group to hold all resources
resource resourceGroup 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: '${abbrs.resourcesResourceGroups}${environmentName}'
  location: location
  tags: tags
}

// The Azure Container Registry to hold the images
module acr './resources/acr.bicep' = {
  name: 'container-registry'
  scope: resourceGroup
  params: {
    location: location
    name: '${abbrs.containerRegistryRegistries}${resourceToken}'
    tags: tags
  }
}

// The AKS cluster to host the application
module aks './resources/aks.bicep' = {
  name: 'aks'
  scope: resourceGroup
  params: {
    location: location
    name: '${abbrs.containerServiceManagedClusters}${resourceToken}'
    kubernetesVersion: kubernetesVersion
    vmSize: nodeVmSize
    nodeCount: nodeCount
    logAnalyticsId: monitoring.outputs.logAnalyticsWorkspaceId
    tags: tags
  }
}

// Grant ACR Pull access from cluster managed identity to container registry
module containerRegistryAccess './role-assignments/aks-acr-role-assignment.bicep' = {
  name: 'cluster-container-registry-access'
  scope: resourceGroup
  params: {
    aksPrincipalId: aks.outputs.clusterIdentity.objectId
    acrName: acr.outputs.name
    desc: 'AKS cluster managed identity'
  }
}

// Monitor application with Azure Monitor
module monitoring './monitoring/monitoring.bicep' = {
  name: 'monitoring'
  scope: resourceGroup
  params: {
    location: location
    azureMonitorWorkspaceLocation: location
    grafanaLocation: grafanaLocation
    logAnalyticsName: '${abbrs.operationalInsightsWorkspaces}${resourceToken}'
    containerInsightsName: '${abbrs.containerInsights}${resourceToken}'
    azureMonitorName: '${abbrs.monitor}${resourceToken}'
    azureManagedGrafanaName: '${abbrs.grafanaWorkspace}${resourceToken}'
    clusterName: '${abbrs.containerServiceManagedClusters}${resourceToken}'
    tags: tags
  }
}

// Azure Monitor rule association with the AKS cluster to enable the portal experience
module ruleAssociations 'monitoring/rule-associations.bicep' = {
  name: 'monitoring-rules-associations'
  scope: resourceGroup
  params: {
    clusterName: aks.outputs.name
    prometheusDcrId: monitoring.outputs.prometheusDcrId
    containerInsightsDcrId: monitoring.outputs.containerInsightsDcrId
  }
}

// Rol Grafana Admin para quien ejecuta azd, para poder entrar a Grafana y crear el tablero
module grafanaAdmin 'role-assignments/grafana-role-assignment.bicep' = if (!empty(principalId)) {
  name: 'grafana-admin-role'
  scope: resourceGroup
  params: {
    principalId: principalId
    principalType: principalType
    grafanaName: monitoring.outputs.grafanaName
    desc: 'Usuario que ejecuta azd'
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_SUBSCRIPTION_ID string = subscription().subscriptionId
output AZURE_AKS_CLUSTER_NAME string = aks.outputs.name
output AZURE_KUBERNETES_VERSION string = aks.outputs.kubernetesVersion
output AZURE_RESOURCE_GROUP string = resourceGroup.name
output AZURE_AKS_CLUSTERIDENTITY_OBJECT_ID string = aks.outputs.clusterIdentity.objectId
output AZURE_AKS_CLUSTERIDENTITY_CLIENT_ID string = aks.outputs.clusterIdentity.clientId
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = acr.outputs.loginServer
output AZURE_CONTAINER_REGISTRY_NAME string = acr.outputs.name
output AZURE_MANAGED_PROMETHEUS_ENDPOINT string = monitoring.outputs.prometheusEndpoint
output AZURE_MANAGED_PROMETHEUS_NAME string = monitoring.outputs.azureMonitorWorkspaceName
output AZURE_MANAGED_GRAFANA_ENDPOINT string = monitoring.outputs.grafanaDashboard
output AZURE_MANAGED_PROMETHEUS_RESOURCE_ID string = monitoring.outputs.azureMonitorWorkspaceId
output AZURE_MANAGED_GRAFANA_RESOURCE_ID string = monitoring.outputs.grafanaId
output AZURE_MANAGED_GRAFANA_NAME string = monitoring.outputs.grafanaName
output PROMETHEUS_ENDPOINT string = monitoring.outputs.prometheusEndpoint
