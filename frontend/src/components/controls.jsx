/**
 * Form controls.
 *
 * The native `<select>` is the single loudest "this is a student project" signal
 * in a web app: it renders in the operating system's style, ignores the
 * surrounding design entirely, and looks different on every machine you demo on.
 * These replace the three controls that mattered -- a listbox, a switch and a
 * segmented control -- while keeping the keyboard behaviour the native elements
 * gave us for free, because losing that would be a real regression rather than a
 * cosmetic one.
 */

import { useEffect, useId, useMemo, useRef, useState } from 'react'

import { Icon } from './ui'

/** Close when the user clicks anywhere outside `ref`. */
function useDismiss(ref, onDismiss, active) {
  useEffect(() => {
    if (!active) return
    const onPointer = (event) => {
      if (ref.current && !ref.current.contains(event.target)) onDismiss()
    }
    const onKey = (event) => {
      if (event.key === 'Escape') onDismiss()
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [ref, onDismiss, active])
}

/**
 * A styled listbox.
 *
 * `options` is `[{ value, label, hint? }]`. A search box appears once the list
 * is long enough to be worth filtering -- the product list runs to thirty
 * entries, and scrolling that blind is worse than the native control was.
 */
export function Select({
  value,
  onChange,
  options,
  placeholder = 'Select…',
  disabled = false,
  searchable,
  id,
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const wrapper = useRef(null)
  const listRef = useRef(null)
  const searchRef = useRef(null)
  const generatedId = useId()
  const controlId = id || generatedId

  useDismiss(wrapper, () => setOpen(false), open)

  const withSearch = searchable ?? options.length > 8
  const selected = options.find((option) => option.value === value)

  const filtered = useMemo(() => {
    if (!query.trim()) return options
    const needle = query.trim().toLowerCase()
    return options.filter((option) => option.label.toLowerCase().includes(needle))
  }, [options, query])

  useEffect(() => {
    if (!open) {
      setQuery('')
      return
    }
    const index = options.findIndex((option) => option.value === value)
    setActive(index >= 0 ? index : 0)
    if (withSearch) requestAnimationFrame(() => searchRef.current?.focus())
  }, [open, options, value, withSearch])

  // Keep the highlighted row inside the scroll viewport.
  useEffect(() => {
    if (!open || !listRef.current) return
    const node = listRef.current.querySelector('[data-active="true"]')
    node?.scrollIntoView({ block: 'nearest' })
  }, [active, open])

  const commit = (option) => {
    onChange(option.value)
    setOpen(false)
  }

  const onKeyDown = (event) => {
    if (!open) {
      if (['Enter', ' ', 'ArrowDown'].includes(event.key)) {
        event.preventDefault()
        setOpen(true)
      }
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((i) => Math.min(filtered.length - 1, i + 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((i) => Math.max(0, i - 1))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      if (filtered[active]) commit(filtered[active])
    } else if (event.key === 'Tab') {
      setOpen(false)
    }
  }

  return (
    <div ref={wrapper} className="relative">
      <button
        type="button"
        id={controlId}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={onKeyDown}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={`form-input flex items-center justify-between gap-2 text-left
                    ${open ? 'ring-2 ring-brand-500 shadow-[0_0_0_4px_rgb(99_102_241_/_0.10)]' : ''}
                    ${disabled ? 'cursor-not-allowed' : 'cursor-pointer'}`}
      >
        <span className={`truncate ${selected ? 'text-slate-900' : 'text-slate-400'}`}>
          {selected?.label ?? placeholder}
        </span>
        <Icon.ChevronDown
          className={`w-4 h-4 shrink-0 text-slate-400 transition-transform duration-200
                      ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div
          className="absolute z-50 mt-2 w-full rounded-xl bg-white shadow-card-xl
                     ring-1 ring-slate-900/[0.08] overflow-hidden animate-slide-down"
        >
          {withSearch && (
            <div className="p-2 border-b border-slate-100">
              <div className="relative">
                <Icon.Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  ref={searchRef}
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value)
                    setActive(0)
                  }}
                  onKeyDown={onKeyDown}
                  placeholder="Search…"
                  className="w-full pl-8 pr-2 py-1.5 text-sm rounded-lg bg-slate-50
                             ring-1 ring-transparent focus:ring-brand-500 focus:bg-white
                             focus:outline-none transition-all"
                />
              </div>
            </div>
          )}

          <ul
            ref={listRef}
            role="listbox"
            className="max-h-64 overflow-y-auto p-1.5"
          >
            {filtered.length === 0 && (
              <li className="px-3 py-6 text-center text-sm text-slate-400">
                Nothing matches “{query}”
              </li>
            )}
            {filtered.map((option, index) => {
              const isSelected = option.value === value
              return (
                <li key={option.value}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    data-active={index === active}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => commit(option)}
                    className={`w-full text-left px-3 py-2 rounded-lg text-sm flex items-start
                                gap-2 transition-colors duration-100
                                ${index === active ? 'bg-brand-50' : ''}
                                ${isSelected ? 'text-brand-800 font-medium' : 'text-slate-700'}`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate">{option.label}</span>
                      {option.hint && (
                        <span className="block text-[11px] text-slate-400 truncate mt-0.5">
                          {option.hint}
                        </span>
                      )}
                    </span>
                    {isSelected && (
                      <Icon.Check className="w-4 h-4 shrink-0 text-brand-600 mt-0.5" />
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}
    </div>
  )
}

/** An on/off switch. Replaces the native checkbox, which cannot be styled well. */
export function Toggle({ checked, onChange, label, hint, disabled = false }) {
  const id = useId()
  return (
    <div className="flex items-start gap-3">
      <button
        type="button"
        role="switch"
        id={id}
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 shrink-0 w-9 h-5 rounded-full transition-colors duration-200
                    focus-visible:outline-none focus-visible:ring-2
                    focus-visible:ring-brand-500 focus-visible:ring-offset-2
                    ${checked ? 'bg-brand-600' : 'bg-slate-300'}
                    ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow-sm
                      transition-transform duration-200 ease-spring
                      ${checked ? 'translate-x-4' : 'translate-x-0'}`}
        />
      </button>
      <label htmlFor={id} className={`min-w-0 ${disabled ? 'opacity-50' : 'cursor-pointer'}`}>
        <span className="block text-sm font-medium text-slate-700 leading-tight">{label}</span>
        {hint && <span className="block text-[11px] text-slate-400 mt-0.5 leading-relaxed">{hint}</span>}
      </label>
    </div>
  )
}

/**
 * Segmented control with a sliding indicator.
 *
 * Better than a dropdown whenever there are few enough options to show at once:
 * every choice is visible, and switching is one click rather than two.
 */
export function Segmented({ value, onChange, options, size = 'md', className = '' }) {
  const index = Math.max(0, options.findIndex((option) => option.value === value))
  const pad = size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-3.5 py-2 text-sm'

  return (
    <div
      className={`relative inline-flex items-center rounded-xl bg-slate-100/80 p-1
                  ring-1 ring-slate-900/[0.04] ${className}`}
    >
      {/* The moving pill sits behind the labels and is animated by transform,
          which keeps it on the compositor rather than triggering layout. */}
      <span
        className="absolute top-1 bottom-1 rounded-lg bg-white shadow-sm
                   transition-transform duration-300 ease-out-expo"
        style={{
          width: `calc((100% - 0.5rem) / ${options.length})`,
          transform: `translateX(calc(${index} * 100%))`,
          left: '0.25rem',
        }}
      />
      {options.map((option) => {
        const isActive = option.value === value
        const IconComp = option.icon
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={`relative z-10 flex-1 inline-flex items-center justify-center gap-1.5
                        rounded-lg font-medium whitespace-nowrap transition-colors
                        duration-200 ${pad}
                        ${isActive ? 'text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}
          >
            {IconComp && <IconComp className="w-4 h-4" />}
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

/** A number field with steppers, for the forecast horizon. */
export function Stepper({ value, onChange, min = 1, max = 180, step = 1, suffix, presets }) {
  const clamp = (n) => Math.min(max, Math.max(min, n))
  return (
    <div className="space-y-2">
      <div className="flex items-stretch gap-1.5">
        <button
          type="button"
          onClick={() => onChange(clamp(Number(value) - step))}
          className="btn-secondary px-3 py-2 rounded-xl"
          aria-label="Decrease"
        >
          <Icon.Minus className="w-4 h-4" />
        </button>
        <div className="relative flex-1">
          <input
            type="number"
            value={value}
            min={min}
            max={max}
            onChange={(e) => onChange(clamp(Number(e.target.value)))}
            className="form-input text-center font-display font-semibold tabular-nums
                       [appearance:textfield]
                       [&::-webkit-outer-spin-button]:appearance-none
                       [&::-webkit-inner-spin-button]:appearance-none"
          />
          {suffix && (
            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400 pointer-events-none">
              {suffix}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => onChange(clamp(Number(value) + step))}
          className="btn-secondary px-3 py-2 rounded-xl"
          aria-label="Increase"
        >
          <Icon.Plus className="w-4 h-4" />
        </button>
      </div>

      {presets && (
        <div className="flex gap-1.5">
          {presets.map((preset) => (
            <button
              key={preset}
              type="button"
              onClick={() => onChange(preset)}
              className={`flex-1 text-xs py-1.5 rounded-lg font-medium transition-all duration-150
                          ${Number(value) === preset
                            ? 'bg-brand-600 text-white shadow-sm'
                            : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}
            >
              {preset}d
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
