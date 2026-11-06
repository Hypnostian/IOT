param name string
param location string
param kubernetesVersion string

@description('Tamano de los nodos. En Azure for Students (Mexico Central) solo se permiten B v2 y D v4 o posteriores, con 6 vCPU por region.')
param vmSize string = 'Standard_B2as_v2'

@description('Cantidad fija de nodos (sin autoescalado, para no pasar la cuota ni el presupuesto).')
param nodeCount int = 2

@description('Custom tags to apply to the resources')
param tags object = {}

@description('The workspace id of the connected log analytics workspace')
param logAnalyticsId string = ''

// Cambios frente a la plantilla original: API GA en vez de 2023-02-02-preview, nivel Free,
// un solo grupo de nodos pequeno sin autoescalado y disco administrado de 64 GB (los discos
// efimeros no caben en VMs de 2 vCPU). Se quitaron las funciones en vista previa (VPA,
// integracion VNet del API server, bloqueo del grupo de nodos) y los complementos que el
// laboratorio no usa (Azure Policy, Key Vault CSI y enrutamiento de aplicaciones).
resource aks 'Microsoft.ContainerService/managedClusters@2024-09-01' = {
  location: location
  name: name
  tags: tags
  sku: {
    name: 'Base'
    tier: 'Free'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    dnsPrefix: '${name}-dns'
    kubernetesVersion: kubernetesVersion
    enableRBAC: true

    agentPoolProfiles: [
      {
        name: 'systempool'
        mode: 'System'
        count: nodeCount
        enableAutoScaling: false
        vmSize: vmSize
        osType: 'Linux'
        osDiskType: 'Managed'
        osDiskSizeGB: 64
        type: 'VirtualMachineScaleSets'
        maxPods: 110
        enableNodePublicIP: false
        tags: tags
      }
    ]

    // Prometheus administrado: kube-state-metrics y cAdvisor alimentan los tableros de Grafana
    azureMonitorProfile: {
      metrics: {
        enabled: true
        kubeStateMetrics: {
          metricLabelsAllowlist: ''
          metricAnnotationsAllowList: ''
        }
      }
    }

    networkProfile: {
      loadBalancerSku: 'standard'
      networkPlugin: 'azure'
      networkPluginMode: 'overlay'
      outboundType: 'loadBalancer'
    }

    oidcIssuerProfile: {
      enabled: true
    }
    securityProfile: {
      workloadIdentity: {
        enabled: true
      }
    }
    autoUpgradeProfile: {
      upgradeChannel: 'patch'
    }
    addonProfiles: {
      omsAgent: {
        enabled: true
        config: {
          logAnalyticsWorkspaceResourceID: logAnalyticsId
          useAADAuth: 'true'
        }
      }
    }
  }
}

@description('The AKS cluster identity')
output clusterIdentity object = {
  clientId: aks.properties.identityProfile.kubeletidentity.clientId
  objectId: aks.properties.identityProfile.kubeletidentity.objectId
  resourceId: aks.properties.identityProfile.kubeletidentity.resourceId
}
output name string = aks.name
output kubernetesVersion string = aks.properties.currentKubernetesVersion
