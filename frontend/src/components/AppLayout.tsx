import { Layout, Menu, Tag } from 'antd'
import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation } from 'react-router'
import { api } from '../api'

const NAV = [
  { key: '/', label: <Link to="/">Home</Link> },
  { key: '/search', label: <Link to="/search">Search</Link> },
]

function ApiStatus() {
  const [healthy, setHealthy] = useState<boolean | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    api
      .health(controller.signal)
      .then(() => setHealthy(true))
      .catch(() => {
        if (!controller.signal.aborted) setHealthy(false)
      })
    return () => controller.abort()
  }, [])

  if (healthy === null) return <Tag>Checking API…</Tag>
  return healthy ? <Tag color="success">API connected</Tag> : <Tag color="error">API unreachable</Tag>
}

export default function AppLayout() {
  const { pathname } = useLocation()

  return (
    <Layout className="min-h-screen">
      <Layout.Header className="flex items-center gap-6 !px-4">
        <Link to="/" className="shrink-0 text-lg font-semibold !text-white">
          SRA Explorer
        </Link>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[pathname]}
          items={NAV}
          className="min-w-0 flex-1"
        />
        <span className="hidden sm:inline">
          <ApiStatus />
        </span>
      </Layout.Header>

      <Layout.Content>
        <Outlet />
      </Layout.Content>

      <Layout.Footer className="text-center text-sm text-gray-500">
        SRA Explorer · Data from NCBI SRA, NCBI BioProject and ENA
      </Layout.Footer>
    </Layout>
  )
}
