import { Outlet } from 'react-router-dom';
import { TopNav } from './TopNav';

/** 全局布局：顶部导航 fixed，内容区用 pt-14 让位 */
export function AppLayout() {
  return (
    <div className="bg-canvas min-h-full">
      <TopNav />
      <main className="pt-14">
        <div className="mx-auto w-full max-w-7xl px-6 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
