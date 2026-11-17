import { Button, Card, Input, Space, Typography } from 'antd'
import { useState, type ReactNode } from 'react'
import { adminApi } from '../api/admin'
import { ApiError } from '../api/client'

const { Title, Text, Paragraph } = Typography

// The admin pages (/admin/...) are reached only by typing their address and
// ask for a code. The code is not in the page: it is checked by the backend
// (the ADMIN_CODE environment variable, backend/app/admin.py), which also
// checks it on every admin request.
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
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)
  const submit = async () => {
    if (!code || checking) return
    setChecking(true)
    try {
      await adminApi(code).fields()
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? 'Wrong code.' : err instanceof Error ? err.message : 'Wrong code.')
      return
    } finally {
      setChecking(false)
    }
    try {
      sessionStorage.setItem(STORAGE_KEY, code)
    } catch {
      // No storage: the code is only kept for this page view.
    }
    onOpen(code)
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
            status={error ? 'error' : undefined}
            onChange={(e) => {
              setCode(e.target.value)
              setError(null)
            }}
            onPressEnter={submit}
          />
          <Button type="primary" onClick={submit} loading={checking}>
            Open
          </Button>
        </Space.Compact>
        {error && (
          <Text type="danger" className="mt-2 block text-sm">
            {error}
          </Text>
        )}
      </Card>
    </div>
  )
}

// Shows the gate until the code is given, then the page with the code.
export default function AdminGate({ what, children }: { what: string; children: (code: string) => ReactNode }) {
  // A stored code was checked by the backend when it was entered.
  const [code, setCode] = useState<string | null>(storedCode)
  if (!code) return <PasscodeGate what={what} onOpen={setCode} />
  return <>{children(code)}</>
}
