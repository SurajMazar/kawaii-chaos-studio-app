import { theme, type ThemeConfig } from 'antd'

export const PINK = '#ff5d8f'
export const SUN = '#ffd84d'
export const SKY = '#7cc8ff'
export const INK = '#16131a'

export const appTheme: ThemeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: PINK,
    colorWarning: SUN,
    colorInfo: SKY,
    colorSuccess: '#7ed69a',
    colorError: '#ff6b6b',
    colorBgBase: INK,
    colorBgLayout: INK,
    colorBgContainer: '#1f1b24',
    colorBgElevated: '#2a2431',
    colorBorder: '#3a3342',
    colorBorderSecondary: '#2f2937',
    colorTextBase: '#f3eef7',
    borderRadius: 10,
    fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
    fontSize: 14,
  },
  components: {
    Layout: { siderBg: '#1a161f', headerBg: '#1f1b24', bodyBg: INK, headerHeight: 52, headerPadding: '0 16px' },
    Menu: { darkItemBg: '#1a161f', darkSubMenuItemBg: '#1a161f', darkItemSelectedBg: 'rgba(255,93,143,.18)', darkItemSelectedColor: PINK, itemBorderRadius: 8 },
    Card: { headerFontSize: 15 },
    Tabs: { titleFontSize: 14 },
    Tour: { colorPrimary: PINK },
    Steps: { colorPrimary: PINK },
  },
}
