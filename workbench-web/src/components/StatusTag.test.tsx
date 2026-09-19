import { render, screen } from '@testing-library/react'
import { StatusTag } from './StatusTag'

describe('StatusTag', () => {
  it('受控语义色：五种 tone 映射到 AntD 预设色（没有颜色字面量）', () => {
    const { container } = render(
      <>
        <StatusTag tone="success">成功</StatusTag>
        <StatusTag tone="warning">警告</StatusTag>
        <StatusTag tone="danger">危险</StatusTag>
        <StatusTag tone="neutral">中性</StatusTag>
        <StatusTag tone="info">信息</StatusTag>
      </>,
    )
    expect(container.querySelector('.ant-tag-success')).not.toBeNull()
    expect(container.querySelector('.ant-tag-warning')).not.toBeNull()
    expect(container.querySelector('.ant-tag-error')).not.toBeNull()
    expect(container.querySelector('.ant-tag-default')).not.toBeNull()
    expect(container.querySelector('.ant-tag-processing')).not.toBeNull()
  })

  it('四态：各自渲染固定文案，且不使用调用方给的语义色', () => {
    const cases = [
      ['loading', '加载中'],
      ['empty', '暂无'],
      ['error', '加载失败'],
      ['forbidden', '无权限'],
    ] as const

    for (const [state, text] of cases) {
      const { container, unmount } = render(
        <StatusTag tone="success" state={state}>
          成功
        </StatusTag>,
      )
      expect(screen.getByText(text)).toBeInTheDocument()
      expect(screen.queryByText('成功')).not.toBeInTheDocument()
      if (state !== 'loading' && state !== 'error') {
        expect(container.querySelector('.ant-tag-success')).toBeNull()
      }
      unmount()
    }
  })

  it('状态保真：数据非就绪时不贴语义色，也不显示"成功"', () => {
    const { container } = render(
      <StatusTag tone="success" presence="unverified">
        成功
      </StatusTag>,
    )
    expect(screen.getByText('未验证')).toBeInTheDocument()
    expect(screen.queryByText('成功')).not.toBeInTheDocument()
    expect(container.querySelector('.ant-tag-success')).toBeNull()
    expect(container.querySelector('.ant-tag-default')).not.toBeNull()
  })
})