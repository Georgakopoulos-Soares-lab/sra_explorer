import { Button, Card, Input, Space, Typography } from 'antd'
import { useState, type ReactNode } from 'react'

const { Title, Text, Paragraph } = Typography

// The admin pages (/admin/...) are reached only by typing their address and
// ask for this code. It is a simple gate, not security: the code is in the
// page's JavaScript. What protects the database is the backend, which checks
// the same code on every admin request (ADMIN_CODE in backend/app/admin.py).
export const ADMIN_CODE = 'srageek'
const STORAGE_KEY = 'srascout-admin-code'

// Remembered for the browser tab, so a reload (or the other admin page)
// doesn't ask again.
function storedCode(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function PasscodeGate({ what, onOpen }: { what: string; onOpen: (code: string) => void }) {
  const [code, setCode] = useState('')
  const [wrong, setWrong] = useState(false)
  const submit = () => {
    if (code === ADMIN_CODE) {
      try {
        sessionStorage.setItem(STORAGE_KEY, code)
      } catch {
        // No storage: the code is only kept for this page view.
      }
      onOpen(code)
    } else {
      setWrong(true)
    }
  }
  return (
    <div className="mx-auto max-w-sm px-4 py-20">
      <Card>
        <Title level={4}>Admin</Title>
        <Paragraph type="secondary">Enter the code to open the {what} page.</Paragraph>
        <Space.Compact className="w-full">
          <Input.Password
            autoFocus
            placeholder="Code"
            value={code}
            status={wrong ? 'error' : undefined}
            onChange={(e) => {
              setCode(e.target.value)
              setWrong(false)
            }}
            onPressEnter={submit}
          />
          <Button type="primary" onClick={submit}>
            Open
          </Button>
        </Space.Compact>
        {wrong && (
          <Text type="danger" className="mt-2 block text-sm">
            Wrong code.
          </Text>
        )}
      </Card>
    </div>
  )
}

// Shows the gate until the code is given, then the page with the code.
export default function AdminGate({ what, children }: { what: string; children: (code: string) => ReactNode }) {
  const [code, setCode] = useState<string | null>(() => (storedCode() === ADMIN_CODE ? ADMIN_CODE : null))
  if (!code) return <PasscodeGate what={what} onOpen={setCode} />
  return <>{children(code)}</>
}
