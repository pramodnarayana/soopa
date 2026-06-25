import { Route as rootRoute } from './routes/__root'
import { Route as marketingRoute } from './routes/_marketing'
import { Route as landingRoute } from './routes/_marketing/index'
import { Route as appRoute } from './routes/_app'
import { Route as dashboardRoute } from './routes/_app/dashboard'

export const routeTree = rootRoute.addChildren([
  marketingRoute.addChildren([landingRoute]),
  appRoute.addChildren([dashboardRoute])
])
