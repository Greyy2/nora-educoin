import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = path.resolve(frontendDir, '../../..')
const projectPython = '/home/vmc03/.venvs/nora312/bin/python'
const python = process.env.NORA_PYTHON || (existsSync(projectPython) ? projectPython : 'python3')
const schemaScript = 'from backend.main import app; import json; print(json.dumps(app.openapi()["paths"]))'

function getPaths(product) {
  const result = spawnSync(python, ['-c', schemaScript], {
    cwd: path.join(repoRoot, 'nora', product),
    encoding: 'utf8',
  })
  if (result.error) throw result.error
  if (result.status !== 0) {
    throw new Error(`${product} OpenAPI generation failed:\n${result.stderr}`)
  }

  const output = result.stdout.trim().split(/\r?\n/).at(-1)
  try {
    return new Set(Object.keys(JSON.parse(output)))
  } catch (error) {
    throw new Error(`${product} did not emit a valid OpenAPI paths object: ${error.message}`)
  }
}

function readRequestPathPrefixes(source) {
  const prefixes = new Set()
  const requestStart = /\brequest\s*\(\s*(['"`])([^\r\n]*)/g

  for (const match of source.matchAll(requestStart)) {
    const quote = match[1]
    let value = match[2].split(quote, 1)[0]
    if (!value.startsWith('/api/')) continue

    const dynamicPart = value.indexOf('${')
    if (dynamicPart !== -1) value = value.slice(0, dynamicPart)
    value = value.split('?', 1)[0]
    if (value) prefixes.add(value)
  }

  return prefixes
}

function prefixExists(prefix, paths) {
  return [...paths].some((route) => {
    const concreteRoute = route.replace(/\{[^/]+\}/g, 'parameter')
    return concreteRoute === prefix || concreteRoute.startsWith(prefix)
  })
}

try {
  const availablePaths = new Set([...getPaths('coin'), ...getPaths('edu')])
  let checked = 0
  const missing = []

  for (const product of ['coin', 'edu']) {
    const apiFile = path.join(repoRoot, 'nora', product, 'frontend', 'src', 'api.js')
    const source = await readFile(apiFile, 'utf8')
    const prefixes = readRequestPathPrefixes(source)
    checked += prefixes.size

    for (const prefix of prefixes) {
      if (!prefixExists(prefix, availablePaths)) missing.push(`${product}: ${prefix}`)
    }
  }

  if (missing.length) {
    console.error('API helper path prefixes missing from both product OpenAPI schemas:')
    for (const entry of missing) console.error(`  - ${entry}`)
    process.exitCode = 1
  } else {
    console.log(`PASS: ${checked} static API helper path prefixes exist in COIN or EDU OpenAPI.`)
    console.log('This is a route-existence check; request/response schemas and authorization require product tests.')
  }
} catch (error) {
  console.error(error.message)
  process.exitCode = 1
}
