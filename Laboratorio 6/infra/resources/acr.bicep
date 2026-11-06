@description('The name of the Azure Container Registry.')
param name string

@description('The location of the Azure Container Registry.')
param location string

@description('Custom tags to apply to the resources')
param tags object = {}

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: name
  location: location
  sku: {
    name: 'Basic' // la plantilla usa Standard; Basic basta porque los portales usan imagenes publicas
  }
  properties: {
    adminUserEnabled: false
  }
  tags: tags
}

output name string = containerRegistry.name
output loginServer string = containerRegistry.properties.loginServer
