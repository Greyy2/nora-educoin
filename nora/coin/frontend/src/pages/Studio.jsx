import React from 'react'
import StudioWorkspace from '../components/alpha/studio/StudioWorkspace'

export default function Studio({ mode = 'create' }) {
  return <StudioWorkspace mode={mode} />
}
