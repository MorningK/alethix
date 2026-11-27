import type { ThemeConfig } from 'antd';

/** 纸感主题的原始色值与字体，供配置、标签和细节 CSS 统一引用。 */
export const PAPER_COLORS = {
  canvas: '#fffdf7',
  surface: '#ffffff',
  surfaceMuted: '#f8f2e4',
  surfaceWarm: '#fffbeb',
  text: '#3b2f2f',
  textSecondary: '#6b5b4b',
  textSubtle: '#a79880',
  border: '#efe5d0',
  borderStrong: '#d8c7a7',
  primary: '#b45309',
  primaryHover: '#92400e',
  primaryActive: '#78350f',
  accent: '#d97706',
  success: '#059669',
  warning: '#d97706',
  danger: '#dc2626',
  info: '#b45309',
  codeBg: '#f8f2e4',
  fontSans: '"PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
  fontHeading: '"Cormorant Garamond", "Noto Serif SC", "Songti SC", Georgia, serif',
  shadowSm: '0 1px 2px rgba(59, 47, 47, 0.07)',
  shadowMd: '0 10px 30px rgba(59, 47, 47, 0.1)',
} as const;

/** Ant Design 全局主题配置；@ant-design/x 共用同一 ConfigProvider 上下文。 */
export const paperTheme: ThemeConfig = {
  token: {
    colorPrimary: PAPER_COLORS.primary,
    colorPrimaryHover: PAPER_COLORS.primaryHover,
    colorPrimaryActive: PAPER_COLORS.primaryActive,
    colorBgBase: PAPER_COLORS.surface,
    colorBgContainer: PAPER_COLORS.surface,
    colorBgElevated: PAPER_COLORS.surface,
    colorBgLayout: PAPER_COLORS.canvas,
    colorText: PAPER_COLORS.text,
    colorTextSecondary: PAPER_COLORS.textSecondary,
    colorTextTertiary: PAPER_COLORS.textSubtle,
    colorBorder: PAPER_COLORS.border,
    colorBorderSecondary: PAPER_COLORS.border,
    colorSuccess: PAPER_COLORS.success,
    colorWarning: PAPER_COLORS.warning,
    colorError: PAPER_COLORS.danger,
    colorInfo: PAPER_COLORS.info,
    colorLink: PAPER_COLORS.primary,
    fontFamily: PAPER_COLORS.fontSans,
    fontSize: 14,
    borderRadius: 10,
    borderRadiusLG: 14,
    controlHeight: 36,
    boxShadowSecondary: PAPER_COLORS.shadowMd,
  },
  components: {
    Button: {
      primaryShadow: 'none',
      defaultShadow: 'none',
      dangerShadow: 'none',
    },
    Table: {
      headerBg: PAPER_COLORS.surfaceMuted,
      headerColor: PAPER_COLORS.textSecondary,
      rowHoverBg: PAPER_COLORS.surfaceWarm,
      borderColor: PAPER_COLORS.border,
    },
    Card: {
      headerBg: PAPER_COLORS.surface,
    },
    Tag: {
      defaultBg: PAPER_COLORS.surfaceMuted,
      defaultColor: PAPER_COLORS.textSecondary,
    },
  },
};
