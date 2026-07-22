import { createFileRoute, redirect } from '@tanstack/react-router'

export const Route = createFileRoute('/tenant/')({
  beforeLoad: () => {
    throw redirect({
      to: '/tenant/explorer',
    })
  },
})
