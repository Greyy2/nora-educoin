#!/usr/bin/env node
// scripts/checkApi.mjs
// So sánh mọi hàm gọi trong frontend/src/api.js với OpenAPI từ backend (FastAPI).
// Báo lỗi nếu frontend gọi endpoint không tồn tại trong OpenAPI.

import fs from 'node:fs'
import path from 'node:path'
import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.resolve(__dirname, '../..')
const API_JS = path.resolve(__dirname, '../src/api.js')

async function getOpenApi() {
  try {
    const res = await fetch('http://127.0.0.1:18010/openapi.json', { signal: AbortSignal.timeout(2000) })
    if (res.ok) return await res.json()
  } catch (_) {}

  // Fallback chạy trực tiếp từ python FastAPI app
  const pyOut = execSync(
    '/home/vmc03/.venvs/nora/bin/python -c "import json; from backend.main import app; print(json.dumps(app.openapi()))"',
    { cwd: ROOT, encoding: 'utf-8', maxBuffer: 10 * 1024 * 1024 }
  )
  return JSON.parse(pyOut)
}

function normalizePath(raw) {
  let s = raw.trim()
  // Loại bỏ query string và các cú pháp nối query
  s = s.replace(/\?.*$/, '')
  s = s.replace(/\$\{_?qs\(.*$/, '')
  s = s.replace(/\$\{qsStr.*$/, '')
  // Thay biến hằng số FR
  s = s.replace(/\$\{FR\}/g, '/api/studio/funnel/runs')
  s = s.replace(/\bFR\b/g, '/api/studio/funnel/runs')

  // Chuyển ${enc(x)} hoặc ${x} thành {param}
  s = s.replace(/\$\{enc\(([a-zA-Z0-9_]+)\)\}/g, '{$1}')
  s = s.replace(/\$\{([a-zA-Z0-9_]+)\}/g, '{$1}')

  // Xử lý các phép cộng chuỗi kiểu: '/path/' + enc(id)
  s = s.replace(/['"`]\s*\+\s*enc\(([a-zA-Z0-9_]+)\)\s*\+\s*['"`]/g, '{$1}')
  s = s.replace(/['"`]\s*\+\s*enc\(([a-zA-Z0-9_]+)\)/g, '{$1}')
  s = s.replace(/['"`]\s*\+\s*([a-zA-Z0-9_]+)\s*\+\s*['"`]/g, '{$1}')
  s = s.replace(/['"`]\s*\+\s*([a-zA-Z0-9_]+)/g, '{$1}')

  // Bỏ dấu nháy còn sót
  s = s.replace(/['"`]/g, '')

  // Chuẩn hoá tên param theo quy ước OpenAPI
  s = s.replace(/\{runId\}/g, '{run_id}')
  s = s.replace(/\{id\}/g, '{run_id}') // nếu đứng sau runs
  s = s.replace(/runs\/\{run_id\}/g, 'runs/{run_id}')
  s = s.replace(/jobs\/\{run_id\}/g, 'jobs/{job_id}')
  s = s.replace(/jobs\/\{id\}/g, 'jobs/{job_id}')
  s = s.replace(/source\/\{id\}/g, 'source/{strategy_id}')
  s = s.replace(/alphas\/\{alphaId\}/g, 'alphas/{alpha_id}')
  s = s.replace(/alphas\/\{id\}/g, 'alphas/{alpha_id}')
  s = s.replace(/user\/\{alphaId\}/g, 'user/{alpha_id}')
  return s
}

async function main() {
  console.log('🔍 Đang kiểm tra API client (frontend/src/api.js) với OpenAPI...')
  const openapi = await getOpenApi()
  const openapiPaths = openapi.paths || {}

  // Xây dựng tập hợp các [METHOD path] trong OpenAPI
  const openapiOps = new Set()
  for (const [pathKey, methods] of Object.entries(openapiPaths)) {
    for (const m of Object.keys(methods)) {
      openapiOps.add(`${m.toUpperCase()} ${pathKey}`)
    }
  }

  // Đọc api.js và trích xuất các export gọi request(...)
  const content = fs.readFileSync(API_JS, 'utf-8')
  
  // Tách từng khối export
  const exportBlocks = content.split(/export\s+(?:async\s+)?(?:function|const)\s+/)
  const calls = []

  for (let i = 1; i < exportBlocks.length; i++) {
    const block = exportBlocks[i]
    const funcNameMatch = /^([a-zA-Z0-9_]+)/.exec(block)
    const funcName = funcNameMatch ? funcNameMatch[1] : `anonymous_${i}`

    // Bỏ qua các export không gọi request (như ApiError, etc.)
    if (!block.includes('request(')) continue

    // Tìm URL bên trong request(...)
    // Format: request(<url>, { ... method: '<METHOD>' ... })
    const reqMatch = /request\(\s*(`[^`]+`|'[^']+'|"[^"]+"|[a-zA-Z0-9_]+(?:\s*\+\s*[^,\)]+)?)/.exec(block)
    if (!reqMatch) continue

    let rawUrl = reqMatch[1].trim()
    let method = 'GET'
    const methodMatch = /method:\s*['"]([A-Z]+)['"]/i.exec(block)
    if (methodMatch) {
      method = methodMatch[1].toUpperCase()
    }

    const normUrl = normalizePath(rawUrl)
    calls.push({ funcName, rawUrl, method, normUrl })
  }

  console.log(`📡 Tìm thấy ${calls.length} API client functions trong frontend/src/api.js.`)
  console.log(`📋 OpenAPI có ${openapiOps.size} operations.`)

  let errors = 0
  const matched = new Set()

  for (const call of calls) {
    const key = `${call.method} ${call.normUrl}`
    if (openapiOps.has(key)) {
      matched.add(key)
    } else {
      // Regex so khớp tham số {param}
      let found = false
      for (const opKey of openapiOps) {
        const [opMethod, opPath] = opKey.split(' ')
        if (opMethod === call.method) {
          const reg = new RegExp('^' + opPath.replace(/\{[^}]+\}/g, '[^/]+') + '$')
          if (reg.test(call.normUrl) || reg.test(call.normUrl.replace(/\{[^}]+\}/g, 'x'))) {
            found = true
            matched.add(opKey)
            break
          }
        }
      }
      if (!found) {
        console.error(`❌ KHÔNG TÌM THẤY TRONG OPENAPI: [${call.funcName}] ${call.method} ${call.normUrl} (raw: ${call.rawUrl})`)
        errors++
      }
    }
  }

  console.log(`✅ Khớp thành công: ${matched.size} operations trong OpenAPI.`)

  if (errors > 0) {
    console.error(`💥 Phát hiện ${errors} API client functions không khớp với backend OpenAPI!`)
    process.exit(1)
  }

  console.log('🎉 Toàn bộ API client functions trong frontend/src/api.js khớp chuẩn 100% với OpenAPI!')
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
