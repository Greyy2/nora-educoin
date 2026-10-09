import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const filePath = path.join(__dirname, 'src/components/education/educationSamples.js')

// Read file content
const raw = fs.readFileSync(filePath, 'utf-8')

// Extract JSON array after "export const EDU_SAMPLES = "
const jsonStart = raw.indexOf('[')
const jsonEnd = raw.lastIndexOf(']')
if (jsonStart === -1 || jsonEnd === -1) {
  console.error("Could not find array in educationSamples.js")
  process.exit(1)
}

const jsonStr = raw.slice(jsonStart, jsonEnd + 1)
const samples = JSON.parse(jsonStr)

console.log(`Found ${samples.length} strategies. Enriching code with English explanations...`)

function enrichCode(code, name, category) {
  const lines = code.split('\n')
  const algoIdx = lines.findIndex(l => l.includes('def __algorithm__(self):'))
  if (algoIdx === -1) return code

  const preAlgo = lines.slice(0, algoIdx + 1)
  const bodyLines = lines.slice(algoIdx + 1)

  const bucketData = []
  const bucketFeat = []
  const bucketSig = []
  const bucketPos = []

  for (const line of bodyLines) {
    const s = line.trim()
    if (!s) continue
    if (s.startsWith('#')) continue // skip existing comments if any
    
    if (s.includes('self.set_positions')) {
      bucketPos.push(line)
    } else if (
      s.includes('enter_') || s.includes('exit_') || s.includes('bullish_') ||
      s.includes('bearish_') || s.includes('oversold_') || s.includes('rebound_') ||
      s.includes('aligned') || s.includes('trigger') || s.includes('breakout_') ||
      s.includes('trailing_')
    ) {
      bucketSig.push(line)
    } else if (s.includes('self.data.')) {
      bucketData.push(line)
    } else {
      bucketFeat.push(line)
    }
  }

  const newBody = [
    '        # ---------------------------------------------------------------------',
    '        # STEP 1: LOAD CAUSAL MARKET DATA',
    '        # Extract price and volume series from strictly closed historical bars.',
    '        # ---------------------------------------------------------------------',
    ...bucketData,
    '',
    '        # ---------------------------------------------------------------------',
    '        # STEP 2: QUANTITATIVE FEATURE & INDICATOR COMPUTATION',
    '        # Compute technical indicators using causal, Numba-compiled kernels.',
    '        # ---------------------------------------------------------------------',
    ...bucketFeat,
    '',
    '        # ---------------------------------------------------------------------',
    '        # STEP 3: ALPHA LOGIC & SYSTEMATIC SIGNAL GENERATION',
    '        # Formulate vectorized boolean masks for long entry and risk-managed exit.',
    '        # ---------------------------------------------------------------------',
    ...bucketSig,
    '',
    '        # ---------------------------------------------------------------------',
    '        # STEP 4: TARGET PORTFOLIO ALLOCATION & ORDER EXECUTION',
    '        # 0.0 = Flat Cash (Exit/Risk-Off) | 1.0 = 100% Long Target Portfolio Weight.',
    '        # Always evaluate flat exits prior to executing new entries.',
    '        # ---------------------------------------------------------------------',
    ...bucketPos
  ]

  return [...preAlgo, ...newBody, ''].join('\n')
}

const enrichedSamples = samples.map(s => {
  return {
    ...s,
    code: enrichCode(s.code, s.name, s.category)
  }
})

const output = `// Thư viện 50 Mẫu Chiến Lược Định Lượng (50 Quantitative Strategy Templates)
// Chia thành 5 danh mục kinh điển (10 mẫu/danh mục): Trend Following, Mean Reversion, Breakout, Multi-Indicator, Risk-Managed

export const EDU_SAMPLES = ${JSON.stringify(enrichedSamples, null, 2)};
`

fs.writeFileSync(filePath, output, 'utf-8')
console.log(`Successfully enriched all ${enrichedSamples.length} strategies with detailed English comments!`)
