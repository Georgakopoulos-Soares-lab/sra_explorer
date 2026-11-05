import { Layout, Menu } from 'antd'
import { Link, Outlet, useLocation } from 'react-router'
import BrandName from './BrandName'

const NAV = [
  { key: '/', label: <Link to="/">Home</Link> },
  { key: '/search', label: <Link to="/search">Semantic search</Link> },
  { key: '/tags', label: <Link to="/tags">Tag explorer</Link> },
  { key: '/statistics', label: <Link to="/statistics">Statistics</Link> },
  { key: '/docs/api', label: <Link to="/docs/api">API</Link> },
  { key: '/help', label: <Link to="/help">Help</Link> },
]

// Kept apart at the far right: the admin page, not part of the public site.
const ADMIN_NAV = [{ key: '/admin/normalize', label: <Link to="/admin/normalize">Normalization</Link> }]

export default function AppLayout() {
  const { pathname } = useLocation()

  return (
    <Layout className="min-h-screen">
      <Layout.Header className="flex items-center gap-6 !px-4">
        <Link to="/" className="shrink-0 text-xl">
          <BrandName onDark />
        </Link>
        <Menu
          theme="dark"
          mode="horizontal"
          // The files page is part of searching.
          selectedKeys={[pathname.startsWith('/files') ? '/search' : pathname]}
          items={NAV}
          className="min-w-0 flex-1"
        />
        {/* Hidden on phones, where the header has no room for it. */}
        <Menu theme="dark" mode="horizontal" selectedKeys={[pathname]} items={ADMIN_NAV} className="!hidden shrink-0 md:!flex" />
      </Layout.Header>

      <Layout.Content>
        <Outlet />
      </Layout.Content>

      <Layout.Footer className="text-center text-sm text-gray-500">
        SRAscout · Data from NCBI SRA, NCBI BioProject and ENA
      </Layout.Footer>
    </Layout>
  )
}
