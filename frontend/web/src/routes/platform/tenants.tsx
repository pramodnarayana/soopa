import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/platform/tenants')({
  component: RouteComponent,
})

function RouteComponent() {
  return <div>Hello "/_platform/tenants"!</div>
}
